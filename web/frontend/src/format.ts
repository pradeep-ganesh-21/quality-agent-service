import { stringifyJson } from './json';
import type { JsonNumber, JsonValue } from './types';

export function formatTimestamp(value: string | null): string {
  // API timestamps are validated at the fetch boundary. Invalid input must not become a date.
  if (value === null) return 'unknown';
  return new Date(value).toISOString().replace('T', ' ').replace('Z', ' UTC');
}

export function formatCount(value: JsonNumber | null | undefined): string {
  return value == null ? 'unknown' : value.toString();
}

export function formatJson(value: JsonValue): string {
  return stringifyJson(value, 2);
}
