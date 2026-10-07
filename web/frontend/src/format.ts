import { stringifyJson } from './json';
import type { JsonNumber, JsonValue } from './types';

export function padNumber(value: number, width = 2): string {
  return value.toString().padStart(width, '0');
}

/**
 * Render an API timestamp in the browser time zone.
 *
 * Each view states the zone once, so individual values carry no suffix. The
 * underlying `dateTime` attributes keep the original UTC text.
 */
export function formatTimestamp(value: string | null): string {
  // API timestamps are validated at the fetch boundary. Invalid input must not become a date.
  if (value === null) return 'unknown';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) throw new RangeError('Invalid time value');
  const calendar = `${padNumber(date.getFullYear(), 4)}-${padNumber(date.getMonth() + 1)}-${padNumber(date.getDate())}`;
  const clock = `${padNumber(date.getHours())}:${padNumber(date.getMinutes())}:${padNumber(date.getSeconds())}`;
  return `${calendar} ${clock}.${padNumber(date.getMilliseconds(), 3)}`;
}

/** Name the browser time zone, so a displayed local time is unambiguous. */
export function localZoneLabel(): string {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (zone !== undefined && zone !== '') return zone;
  // Without a resolved zone name, report the current offset instead.
  const offset = -new Date().getTimezoneOffset();
  const magnitude = Math.abs(offset);
  return `UTC${offset < 0 ? '-' : '+'}${padNumber(Math.trunc(magnitude / 60))}:${padNumber(magnitude % 60)}`;
}

export function formatCount(value: JsonNumber | null | undefined): string {
  return value == null ? 'unknown' : value.toString();
}

export function formatJson(value: JsonValue): string {
  return stringifyJson(value, 2);
}
