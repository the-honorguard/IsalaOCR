# IsalaOCR 3.7.3 — Fast exception-based detection review

Detection Review Studio is optimized for large review sets. Open candidates are treated in the UI as provisional **Correct + Relevant**. Reviewers only touch exceptions; **Bron afronden & volgende** commits all remaining open candidates for the current source in one bulk operation and moves to the next source that still has open candidates.

Out-of-scope review no longer requires a dropdown. Seven direct reason buttons are available and immediately save the candidate as geometrically correct but irrelevant, then advance to the next open candidate. Keyboard keys `1` through `7` trigger the same reasons. `X` marks a false positive, `A` saves adjusted geometry, arrow keys navigate open candidates and `F` finishes the source.

The underlying review semantics and localization dataset remain unchanged: only explicitly reviewed exceptions are stored immediately; candidates accepted through source finalization are persisted as Correct + Relevant. Ignore regions remain ignore regions and are not converted into localization negatives.
