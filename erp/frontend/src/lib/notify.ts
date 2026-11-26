import type { MessageInstance } from 'antd/es/message/interface';

/**
 * Toast messages for code that runs outside React (axios interceptors, the query cache).
 * `<App>` binds the themed Ant Design message instance once at startup; components should use
 * `App.useApp()` directly.
 */
let instance: MessageInstance | undefined;

export function bindMessage(api: MessageInstance): void {
  instance = api;
}

export const notify = {
  /** A `key` collapses repeated messages (e.g. several parallel requests failing the same way). */
  warning(content: string, key?: string): void {
    void instance?.warning({ content, key });
  },
  error(content: string, key?: string): void {
    void instance?.error({ content, key });
  },
};
