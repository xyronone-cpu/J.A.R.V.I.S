import { createGevActionRunner } from './gevActions.js';
import { createVoiceCommands } from './commands.js';
export * from './realtimeController.js';

/** Compose the standalone action runner with the voice controls. */
export function initGevVoiceCommands(options) {
  const runner = createGevActionRunner(options);
  const commands = createVoiceCommands({
    ...options,
    runner,
  });
  commands.runJarvisAction = (name, args = {}, runOptions = {}) =>
    runner(name, args, runOptions);
  return commands;
}
