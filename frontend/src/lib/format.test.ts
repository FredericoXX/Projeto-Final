import { describe, expect, it } from 'vitest';
import { formatDate, formatFileSize, safeHttpUrl } from './format';

describe('safeHttpUrl', () => {
  it('accepts http and https URLs', () => {
    expect(safeHttpUrl('https://example.edu/doc')).toBe('https://example.edu/doc');
    expect(safeHttpUrl('http://example.edu')).toBe('http://example.edu/');
  });

  it('rejects javascript: and other unsafe protocols', () => {
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull();
    expect(safeHttpUrl('data:text/html,<script>alert(1)</script>')).toBeNull();
    expect(safeHttpUrl('file:///etc/passwd')).toBeNull();
  });

  it('rejects malformed or empty values', () => {
    expect(safeHttpUrl('not a url')).toBeNull();
    expect(safeHttpUrl('')).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
  });
});

describe('formatFileSize', () => {
  it('formats bytes into human units', () => {
    expect(formatFileSize(512, 'en')).toBe('512 B');
    expect(formatFileSize(20480, 'en')).toBe('20 KB');
    expect(formatFileSize(null, 'en')).toBe('—');
  });
});

describe('formatDate', () => {
  it('keeps an ISO calendar date unchanged in negative UTC offsets', () => {
    expect(formatDate('2026-01-01', 'pt')).toBe('01/01/2026');
    expect(formatDate('2026-01-01', 'en')).toBe('1 Jan 2026');
  });

  it('rejects invalid or non-calendar values', () => {
    expect(formatDate('2026-02-30', 'pt')).toBe('—');
    expect(formatDate('not-a-date', 'pt')).toBe('—');
  });
});
