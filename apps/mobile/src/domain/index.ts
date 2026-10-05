/**
 * Domain barrel (§11.1 `src/domain`). Pure TypeScript only — no react-native,
 * expo, zustand or I/O imports (§11.3, enforced by test/purity.test.ts).
 */

export * from './entities';
export * from './sm-stream';
export * from './tokens';
export * from './connection/clock';
export * from './connection/reasons';
export * from './connection/sm-conn';
export * from './connection/race-planner';
