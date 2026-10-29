# Strategy plugin signal envelope V2: consumer binding

This note describes the optional local consumer check. The envelope remains a deterministic, read-only signal contract.

### Consumer binding check

`validate_signal_for_consumer` reuses envelope validation and compares the plugin,
complete producer identity, input provenance and decision date with independently
supplied frozen consumer bindings. It accepts only the same daily cutoff. The
caller must obtain those bindings from trusted configuration; a matching hash or
self-declared identity does not authenticate the producer or prove the input data.
The check conveys no allocation or execution authority and is not a consumption
receipt.

The generic validator retains compatibility when the optional `expected_payload_sha256` is omitted. The UES Global ETF observer requires a separate, valid digest in its trusted binding; missing or invalid values make the observation unavailable.
