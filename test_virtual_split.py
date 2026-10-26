import unittest
from unittest.mock import patch

from bridge_core import Bridge,Pair,virtual_split_offsets,virtual_split_target
from test_bridge import FakeTransport,HOME
from test_native_control import SatellitePanelModel
from rumlog_panel import RumlogPanel


class SplitStateTests(unittest.TestCase):
    def setUp(self):
        self.radio={'rx_hz':433540420,'tx_hz':144040420,'tx_mode':'USB-D'}
        self.writes=[]
        self.fail=False
        self.transmitting=False
        def control(base,offset,remember):
            if self.transmitting:raise RuntimeError('Release PTT')
            origin=self.radio['tx_hz'] if base is None else base
            target=virtual_split_target(origin,offset,self.radio['tx_mode'])
            remember(origin)
            self.writes.append(target)
            self.radio['tx_hz']=target
            if self.fail:raise RuntimeError('TX feedback timed out')
            return {'tx_hz':target,'base_tx_hz':origin}
        self.bridge=Bridge(transport_factory=FakeTransport,power_guard=lambda force=False:1,
                           split_controller=control,radio_reader=lambda:dict(self.radio))
        self.bridge.use_qo100(HOME,'Digital')
        self.bridge.pending=None
        self.bridge.applied_epoch=self.bridge.epoch
        self.bridge.last_sent=HOME
        self.bridge.last_sent_source='qo100'

    def test_ssb_offsets_use_actual_manual_tx_base_and_never_stack(self):
        for offset in (5000,10000,15000):self.bridge.set_virtual_split(offset)
        self.assertEqual(self.writes,[144045420,144050420,144055420])
        self.assertEqual(self.bridge.snapshot()['virtual_split']['base_tx_hz'],144040420)
        self.assertEqual(self.radio['rx_hz'],433540420)
        self.bridge.set_virtual_split(0)
        self.assertEqual(self.radio['tx_hz'],144040420)
        self.assertIsNone(self.bridge.split_base_tx_hz)
        self.assertEqual(self.bridge.transport.calls,[])

    def test_cw_offsets_and_restore(self):
        self.radio['tx_mode']='CW'
        for offset in (1000,2000,3000):self.bridge.set_virtual_split(offset)
        self.bridge.set_virtual_split(0)
        self.assertEqual(self.writes,[144041420,144042420,144043420,144040420])

    def test_manual_tuning_during_split_does_not_replace_the_saved_base(self):
        self.bridge.set_virtual_split(5000)
        self.radio['tx_hz']+=700
        self.bridge.set_virtual_split(0)
        self.assertEqual(self.radio['tx_hz'],144040420)

    def test_off_is_idempotent_and_a_new_activation_captures_a_new_base(self):
        self.bridge.set_virtual_split(0)
        self.assertEqual(self.writes,[])
        self.bridge.set_virtual_split(5000)
        self.bridge.set_virtual_split(0)
        self.radio['tx_hz']=144240000
        self.bridge.set_virtual_split(10000)
        self.assertEqual(self.bridge.split_base_tx_hz,144240000)
        self.assertEqual(self.radio['tx_hz'],144250000)

    def test_preset_or_source_selection_clears_split_without_an_old_base_restore(self):
        for source in ('preset','macdoppler'):
            with self.subTest(source=source):
                self.setUp();self.bridge.set_virtual_split(5000)
                before=list(self.writes)
                if source=='preset':self.bridge.use_qo100(HOME,'Digital')
                else:self.bridge.follow_macdoppler()
                self.assertEqual(self.writes,before)
                self.assertIsNone(self.bridge.split_base_tx_hz)
                self.assertEqual(self.bridge.split_offset_hz,0)

    def test_macdoppler_and_unapplied_qo_cannot_enable_split(self):
        self.bridge.follow_macdoppler()
        with self.assertRaisesRegex(RuntimeError,'QO-100 only'):self.bridge.set_virtual_split(5000)
        self.bridge.use_qo100(HOME,'Digital')
        with self.assertRaisesRegex(RuntimeError,'Apply the QO-100 pair'):self.bridge.set_virtual_split(5000)
        self.assertEqual(self.writes,[])

    def test_partial_failure_retains_the_original_base_for_explicit_off_recovery(self):
        self.fail=True
        with self.assertRaisesRegex(RuntimeError,'TX feedback'):self.bridge.set_virtual_split(5000)
        self.assertEqual(self.bridge.split_base_tx_hz,144040420)
        self.assertEqual(self.writes,[144045420])
        self.assertIsNone(self.bridge.snapshot()['virtual_split']['pending_offset_hz'])
        self.fail=False
        self.bridge.set_virtual_split(0)
        self.assertEqual(self.writes,[144045420,144040420])

    def test_ptt_and_power_failures_do_not_write_or_capture_a_base(self):
        self.transmitting=True
        with self.assertRaisesRegex(RuntimeError,'Release PTT'):self.bridge.set_virtual_split(5000)
        self.assertEqual(self.writes,[])
        self.assertIsNone(self.bridge.split_base_tx_hz)
        self.transmitting=False
        self.bridge.power_guard=lambda force=False:80
        with self.assertRaises(RuntimeError):self.bridge.set_virtual_split(5000)
        self.assertEqual(self.writes,[])

    def test_mode_choices_and_band_limits_are_checked(self):
        self.assertEqual(virtual_split_offsets('CW-R'),(0,1000,2000,3000))
        self.assertEqual(virtual_split_offsets('USB'),(0,5000,10000,15000))
        for value,mode in ((5000,'CW'),(1000,'USB'),(True,'USB'),(-5000,'USB')):
            with self.subTest(value=value,mode=mode),self.assertRaises(ValueError):
                virtual_split_target(144040000,value,mode)
        with self.assertRaises(ValueError):virtual_split_target(147999000,5000,'USB')


class NativeSplitTests(unittest.TestCase):
    def run_native(self,panel,base=None,offset=5000,set_frequency=None):
        clock=[0.0];remembered=[]
        panel.wait=lambda predicate,label,timeout=3:RumlogPanel.wait(panel,predicate,label,timeout)
        with patch('rumlog_panel.time.monotonic',lambda:clock[0]),patch('rumlog_panel.time.sleep',lambda n:clock.__setitem__(0,clock[0]+n)):
            result=panel.apply_virtual_split(base,offset,remembered.append,set_frequency or panel.set_frequency,lambda:None)
        return result,remembered

    def test_only_tx_frequency_changes_with_modes_filters_and_rx_preserved(self):
        panel=SatellitePanelModel()
        result,remembered=self.run_native(panel)
        self.assertEqual(remembered,[144040000])
        self.assertEqual(result['tx_hz'],144045000)
        self.assertEqual(panel.frequency_writes,[('Sub',144045000)])
        self.assertEqual(panel.frequencies['Main'],433540000)
        self.assertEqual(panel.modes,{'Main':'USB-D','Sub':'USB-D'})
        self.assertFalse(any(group=='Mode' for group,name in panel.presses))
        self.assertEqual(panel.band,'Main')
        self.assertTrue(panel.toggling)

    def test_cw_tx_supports_1khz_but_rejects_ssb_offset(self):
        panel=SatellitePanelModel();panel.modes['Sub']='CW'
        result,_=self.run_native(panel,offset=1000)
        self.assertEqual(result['tx_hz'],144041000)
        panel.frequency_writes.clear()
        with self.assertRaises(ValueError):self.run_native(panel,offset=5000)
        self.assertEqual(panel.frequency_writes,[])

    def test_rx_movement_prevents_success_and_never_retries_tx(self):
        panel=SatellitePanelModel()
        def coupled(hz):
            panel.set_frequency(hz)
            panel.frequencies['Main']+=5000
        with self.assertRaisesRegex(RuntimeError,'unchanged RX'):
            self.run_native(panel,set_frequency=coupled)
        self.assertEqual(panel.frequency_writes,[('Sub',144045000)])
        self.assertTrue(panel.toggling)


if __name__=='__main__':unittest.main()
