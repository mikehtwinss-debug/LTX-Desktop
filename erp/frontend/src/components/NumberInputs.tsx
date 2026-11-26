import type { ReactNode } from 'react';

import { DecimalInput, type DecimalInputProps } from './DecimalInput';

type PresetProps = Omit<DecimalInputProps, 'decimals' | 'minDecimals'>;

export interface MoneyInputProps extends PresetProps {
  /** Currency code shown behind the amount. */
  currency?: string | null;
}

/**
 * Amount with two decimals; the value is a decimal string (`"1234.50"`).
 *
 *   <Form.Item name="amount" label="Tutar"><MoneyInput currency="TRY" /></Form.Item>
 */
export function MoneyInput({ currency, ...props }: MoneyInputProps): ReactNode {
  return <DecimalInput suffix={currency || undefined} {...props} decimals={2} />;
}

export interface QtyInputProps extends PresetProps {
  /** Decimals of the unit of measure (`org_uom.decimals`). Default: 3. */
  decimals?: number;
  /** Unit code shown behind the quantity. */
  unit?: string | null;
}

/**
 * Quantity; trailing zeros are not shown.
 *
 *   <Form.Item name="quantity" label="Miktar"><QtyInput decimals={uom.decimals} unit={uom.code} /></Form.Item>
 */
export function QtyInput({ decimals = 3, unit, ...props }: QtyInputProps): ReactNode {
  return <DecimalInput suffix={unit || undefined} {...props} decimals={decimals} minDecimals={0} />;
}

export interface PriceInputProps extends PresetProps {
  currency?: string | null;
}

/**
 * Unit price with up to six decimals, at least two shown.
 *
 *   <Form.Item name="unit_price" label="Birim fiyat"><PriceInput currency={order.currency_code} /></Form.Item>
 */
export function PriceInput({ currency, ...props }: PriceInputProps): ReactNode {
  return <DecimalInput suffix={currency || undefined} {...props} decimals={6} minDecimals={2} />;
}

/**
 * Percentage with up to four decimals (discounts, tax rates, tolerances).
 *
 *   <Form.Item name="discount_pct" label="İskonto"><PctInput /></Form.Item>
 */
export function PctInput(props: PresetProps): ReactNode {
  return <DecimalInput suffix="%" {...props} decimals={4} minDecimals={0} />;
}
