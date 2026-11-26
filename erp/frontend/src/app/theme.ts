import { type MappingAlgorithm, theme, type ThemeConfig } from 'antd';

const PRIMARY = '#1d4f91';
const SIDER_BG = '#15243a';

/**
 * Compact spacing with text one step larger than the stock compact theme (13/12 px instead of
 * 12/10 px), which stays readable over a working day. The line boxes keep their height, so the
 * control sizes of the compact theme are unchanged.
 */
const denseAlgorithm: MappingAlgorithm = (seed, map) => ({
  ...theme.compactAlgorithm(seed, map),
  fontSize: 13,
  lineHeight: 20 / 13,
  fontSizeSM: 12,
  lineHeightSM: 18 / 12,
});

/** Restrained, dense look for table-centric screens: compact controls, small radii, muted navy accent. */
export const appTheme: ThemeConfig = {
  algorithm: denseAlgorithm,
  token: {
    colorPrimary: PRIMARY,
    colorInfo: PRIMARY,
    colorLink: PRIMARY,
    colorBgLayout: '#f2f4f7',
    colorTextBase: '#1c2430',
    borderRadius: 4,
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif",
  },
  components: {
    Layout: {
      headerBg: '#ffffff',
      headerHeight: 46,
      headerPadding: '0 12px',
      siderBg: SIDER_BG,
    },
    Menu: {
      darkItemBg: SIDER_BG,
      darkSubMenuItemBg: '#101c2e',
      darkPopupBg: SIDER_BG,
      darkItemSelectedBg: '#2a62ad',
      itemHeight: 34,
    },
    Table: {
      headerBg: '#eef1f5',
      headerColor: '#3a4656',
      headerSplitColor: '#d9dee6',
      rowHoverBg: '#f3f7fd',
    },
    Form: {
      itemMarginBottom: 12,
    },
  },
};
