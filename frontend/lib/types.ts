export type Endpoint<S extends string> = S extends `/${infer Rest}`
  ? `/${Rest}`
  : `/${S}`;
