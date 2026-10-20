# Cross-product end-to-end test slot

This directory is the confirmed home for future complete-product-flow acceptance tests. It is a test-organization slot, not a test suite, fixture source, product runtime dependency, or evidence that end-to-end behavior has been validated.

Tests added here must exercise public product boundaries and isolated synthetic data. They must not require or copy user run data. Package-specific tests remain with their package owners; cross-package contract and integration tests remain in their designated root test layers.

Current status: no end-to-end tests or supporting test implementation are present here. Product-flow acceptance remains unavailable until real tests are authored and executed.
