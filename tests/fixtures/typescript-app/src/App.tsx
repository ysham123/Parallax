import { total } from './totals.js';
export function App({ values }: { values: number[] }) {
  return <main><h1>Invoice</h1><output>{total(values)}</output></main>;
}
