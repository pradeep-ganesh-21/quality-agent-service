declare module 'core-js-pure/actual/json/parse.js' {
  export default function parse(
    text: string,
    reviver: (key: string, value: unknown, context: { source?: string }) => unknown,
  ): unknown;
}

declare module 'core-js-pure/actual/json/raw-json.js' {
  export default function rawJSON(text: string): { readonly rawJSON: string };
}

declare module 'core-js-pure/actual/json/stringify.js' {
  export default function stringify(
    value: unknown,
    replacer: (key: string, value: unknown) => unknown,
    space?: number,
  ): string | undefined;
}
