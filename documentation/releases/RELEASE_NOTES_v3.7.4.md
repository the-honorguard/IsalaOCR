# IsalaOCR v3.7.4

## Detection Review Studio viewport fix

Selecting a field candidate no longer calls `Element.scrollIntoView()`. In v3.7.3 that call could scroll both the candidate list and the browser document, moving the source image out of view whenever a candidate was selected.

The studio now keeps the current browser/page position unchanged and scrolls only the internal candidate queue when needed. The queue also uses contained overscroll behavior so wheel/trackpad scrolling does not chain into the surrounding page at its boundaries.

No database migration is required. The localization training-image revision remains 3.7.0.
