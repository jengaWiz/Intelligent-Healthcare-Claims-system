# Claim Studio interface design

The workspace is a case file for reviewing extracted claim data. The document,
evidence and next decision define its hierarchy.

## References

[Linear's interface refresh](https://linear.app/now/behind-the-latest-design-refresh)
informed the quiet navigation, consistent location bar and restrained visual weight.
[Ramp's bill approval workflow](https://support.ramp.com/bill-pay-approvals/)
informed the separation of record evidence and reviewer decisions. These are design
references; no product assets, logos or proprietary components are included.

## Visual decisions

- Warm neutral navigation and paper surfaces, with dark ink for primary controls.
  Cobalt identifies links and focus; status colors identify actionable state.
- Sans-serif controls, serif patient headings and monospace identifiers provide
  distinct roles for each type style. Fonts are system-local.
- One claim record contains the stored filename, patient, provider, billed amount
  and dates. Evidence and history follow without repeating the same fields.
- The data decision appears first in the review column. Risk investigation remains
  independent and retains its own reasoned acknowledgment and assessment history.
- Copy names the task directly. Only processing state and risk classification use
  compact colored labels.

## Interaction and verification

Synthetic samples use the same authenticated upload/enqueue path as selected files.
One-click controls are available only in synthetic mode. Real file metadata is
owner-protected, rendered through textContent, and guarded against stale selection.
Audit details and full policy metadata remain accessible through disclosures.

Desktop and 390px mobile browser checks cover the original workflows, one-click
samples, metadata, corrections, duplicates, acknowledgment, conflict recovery,
keyboard-addressable controls and horizontal overflow. README images are actual
synthetic browser captures; source screenshots are not imported from other products.
