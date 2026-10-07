import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import * as format from '../src/format';
import { JsonBlock, JsonValueText } from '../src/JsonBlock';
import { parseJson } from '../src/json';

describe('JSON display', () => {
  it('formats only while expanded, preserves exact numbers, and updates displayed data', async () => {
    const user = userEvent.setup();
    const formatter = vi.spyOn(format, 'formatJson');
    const value = parseJson('{"large":9223372036854775807,"string":"9223372036854775807"}');
    const { rerender } = render(<JsonBlock label="Metadata JSON" value={value} />);
    expect(formatter).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('Metadata JSON', { selector: 'pre' })).not.toBeInTheDocument();
    await user.click(screen.getByText('Metadata JSON', { selector: 'summary' }));
    const pre = await screen.findByLabelText('Metadata JSON', { selector: 'pre' });
    expect(pre).toHaveRole('group');
    expect(pre).toHaveAccessibleName('Metadata JSON');
    expect(pre.textContent).toContain('"large": 9223372036854775807');
    expect(pre.textContent).toContain('"string": "9223372036854775807"');
    rerender(<JsonBlock label="Metadata JSON" value={{ changed: true }} />);
    expect(pre.textContent).toContain('"changed": true');
    await user.click(screen.getByText('Metadata JSON', { selector: 'summary' }));
    expect(screen.queryByLabelText('Metadata JSON', { selector: 'pre' })).not.toBeInTheDocument();
  });

  it('renders HTML-shaped data as literal text, not elements or event handlers', async () => {
    render(<JsonBlock label="Stored JSON" value={{ html: '<img src=x onerror="alert(1)">' }} />);
    const summary = screen.getByText('Stored JSON', { selector: 'summary' });
    fireEvent.click(summary);
    const pre = await screen.findByLabelText('Stored JSON', { selector: 'pre' });
    expect(pre.textContent).toContain('<img');
    expect(document.querySelector('img')).toBeNull();
    expect(document.querySelector('script')).toBeNull();
  });

  it.each([
    [undefined, 'Not provided'], [null, 'null'], [0, '0'], [false, 'false'],
    ['<b>plain text</b>', '<b>plain text</b>'], [9223372036854775807n, '9223372036854775807'],
  ])('distinguishes missing, null, and other leaf values: %s', (value, expected) => {
    const { container } = render(<JsonValueText value={value} />);
    expect(container.textContent).toBe(expected);
    expect(container.querySelector('b')).toBeNull();
  });
});
