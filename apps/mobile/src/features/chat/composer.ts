/**
 * Composer view-model (UI spec 6.5): placeholder and trailing button follow
 * connection state; drafts are kept per conversation.
 */

import type { ConnState } from '../../domain/connection/sm-conn';

export type ComposerButton = 'mic' | 'send' | 'stop';

export interface ComposerVM {
  placeholder: string;
  button: ComposerButton;
  sendDisabled: boolean;
}

export function composerVM(opts: {
  agentName: string;
  conn?: ConnState;
  phoneOffline: boolean;
  text: string;
  streaming: boolean;
}): ComposerVM {
  if (opts.phoneOffline) {
    return { placeholder: "You're offline", button: 'send', sendDisabled: true };
  }
  const connected = opts.conn?.s === 'CONNECTED';
  if (!connected) {
    return { placeholder: `${opts.agentName} is offline`, button: 'send', sendDisabled: true };
  }
  if (opts.streaming) {
    return { placeholder: `Message ${opts.agentName}`, button: 'stop', sendDisabled: false };
  }
  return {
    placeholder: `Message ${opts.agentName}`,
    button: opts.text.trim().length > 0 ? 'send' : 'mic',
    sendDisabled: opts.text.trim().length === 0,
  };
}
