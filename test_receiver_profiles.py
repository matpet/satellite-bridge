import unittest
from unittest.mock import patch
from rumlog_macros import FRONTEND_MACROS,plan_macros
from rumlog_panel import RumlogPanel,ON,OFF
from test_native_control import SatellitePanelModel


class MacroPlanTests(unittest.TestCase):
    def test_receiver_macros_use_unused_manual_slots_and_preserve_automatic_modes(self):
        original=['Existing CW','FE FE A2 E0 17 54 FD']+['']*30+['auto CW','auto data','auto ssb','auto fm']
        changes=plan_macros(original)
        self.assertNotIn(0,changes);self.assertNotIn(1,changes)
        self.assertTrue(all(i<32 for i in changes))
        result=[changes.get(i,v) for i,v in enumerate(original)]
        self.assertEqual(result[32:],original[32:])
        self.assertEqual(plan_macros(result),{})

    def test_conflicting_receiver_macro_cannot_be_run_or_overwritten(self):
        values=['SB RX Off','FE FE A2 E0 1C 00 01 FD']+['']*34
        with self.assertRaisesRegex(RuntimeError,'content differs'):plan_macros(values)

    def test_no_empty_macro_slots_fails_without_changes(self):
        values=sum(([str(i),'01'] for i in range(16)),[])+['']*4
        with self.assertRaisesRegex(RuntimeError,'unused'):plan_macros(values)

    def test_external_preamp_macro_enables_only_70cm_permission_and_selected_band_amps(self):
        self.assertEqual(FRONTEND_MACROS['SB RX Ext'],
                         'FE FE A2 E0 1A 05 00 94 01 FD FE FE A2 E0 16 02 03 FD')
        self.assertEqual(FRONTEND_MACROS['SB RX Off'],'FE FE A2 E0 16 02 00 FD')


class ReceiverPanel(SatellitePanelModel):
    def __init__(self):
        super().__init__()
        self.rf={band:{'ATT':OFF,'PRE':ON,'external':False} for band in ('Main','Sub')}

    def description(self,group,name):
        if group=='Miscellaneous' and name in ('ATT','PRE'):return self.rf[self.band][name]
        return super().description(group,name)

    def press(self,group,name):
        if group=='Miscellaneous' and name=='ATT':
            self.presses.append((group,name));self.rf[self.band]['ATT']=OFF if self.rf[self.band]['ATT']==ON else ON
        elif group=='IC-9700 Macros':
            self.presses.append((group,name))
            self.rf[self.band]['PRE']=OFF if name=='SB RX Off' else ON
            self.rf[self.band]['external']=name=='SB RX Ext'
        else:super().press(group,name)


class ReceiverProfileTests(unittest.TestCase):
    def apply(self,panel,source,hz):
        with patch('rumlog_macros.ensure_frontend_macros'):
            return RumlogPanel.set_rx_frontend(panel,source,hz,lambda:None)

    def test_qo_att_on_amps_off_affects_main_rx_only(self):
        panel=ReceiverPanel();before=dict(panel.rf['Sub'])
        result=self.apply(panel,'qo100',433540000)
        self.assertEqual(panel.rf['Main'],{'ATT':ON,'PRE':OFF,'external':False})
        self.assertEqual(panel.rf['Sub'],before)
        self.assertFalse(result['external_preamp_commanded'])

    def test_leo_70cm_uses_both_preamps_and_disables_rx_att(self):
        panel=ReceiverPanel();panel.rf['Main']['ATT']=ON
        result=self.apply(panel,'macdoppler',433540000)
        self.assertEqual(panel.rf['Main'],{'ATT':OFF,'PRE':ON,'external':True})
        self.assertTrue(result['external_preamp_commanded'])

    def test_leo_two_metre_downlink_does_not_enable_its_external_preamp(self):
        panel=ReceiverPanel();panel.frequencies['Main']=145965000
        self.apply(panel,'macdoppler',145965000)
        self.assertEqual(panel.rf['Main'],{'ATT':OFF,'PRE':ON,'external':False})


if __name__=='__main__':unittest.main()
