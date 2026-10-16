"""
What would dairy-origin cattle have to be, to explain the gap?

The heifers-on-feed series counts every heifer in a feedlot. Some of them were
never a beef-herd retention decision at all: straight Holstein heifers, and the
beef-on-dairy crossbreds that largely replaced them. Neither is a female a
rancher chose not to keep.

THERE IS NO DATA TO REMOVE THEM WITH, and that is worth stating plainly rather
than working around. NASS publishes 21 cattle-on-feed series and not one carries
a breed split. AMS's Direct Cattle Reports are narrative text with no line items.
The only breed detail anywhere is the auction slice -- Dairy and Beef/Dairy
classes in the state summaries -- and that is 0.68% of auction feeder head and
unrepresentative, because beef-on-dairy calves move dairy -> calf ranch ->
feedyard on contract and rarely cross a sale barn.

So this is NOT a correction. It is the inverse question, which the data can
actually speak to: the receipts series IS breed-clean, so instead of guessing how
much dairy is in the feedlot number, ask how much there would have to be for the
two measures to be telling the same story.

    adjusted = (share - h_d * d) / (1 - d)

        d    dairy-origin share of steers+heifers on feed
        h_d  heifer fraction of that dairy-origin stream

With d constant the decline is simply amplified by 1/(1-d), which is why the tool
takes d at BOTH ends: the honest mechanism is a dairy share that grew, not one
that sat still. A constant share large enough to reconcile the two declines comes
out implausible, and that is itself a finding -- it says the reconciliation needs
beef-on-dairy to have been GROWING, which is exactly what the industry did.

WHY THE DIRECTION IS NOT OBVIOUS, and why this is a slider and not an assertion.
Straight Holstein heifers used to be scarce in feedlots -- the legacy AMS archive
carries Feeder Holstein STEERS and no Holstein heifer class at all, because those
heifers became dairy replacements. Sexed semen then produced a surplus that did
go on feed, peaking around the same years this page uses as its rebuild benchmark,
before beef-on-dairy displaced it. So the 2016 low may carry its own dairy-heifer
inflation. The two effects partly offset and neither is measurable, so the net
direction across a decade is genuinely unknown.
"""


# The assumption the beef-only row is drawn at. Stated here rather than handed to
# the reader as a control: this is not a figure anyone knows, so a slider would
# only have let someone dial in the answer they arrived with. The sensitivity
# table beside it shows how far the conclusion moves across the plausible range.
#
#   DAIRY_NOW    mid-point of credible industry estimates, which put
#                dairy-influenced cattle at roughly 15-20% of fed cattle.
#   DAIRY_THEN   zero. The benchmark year certainly carried SOME dairy-origin
#                heifers, and allowing for them would widen every gap the table
#                reports -- so this is the generous footing, and understating the
#                gap is the safer error when the gap is the finding.
#   HEIFER_FRAC  a beef-on-dairy cross is about 50/50 by sex and essentially all
#                of both sexes are fed, neither being wanted as a replacement.
ASSUMED_DAIRY_NOW = 18.0
ASSUMED_DAIRY_THEN = 0.0
ASSUMED_HEIFER_FRAC = 50.0


def adjust(share_pct, dairy_share_pct, heifer_frac_pct):
    """Beef-only heifer share implied by removing a dairy-origin stream.

    All three arguments and the result are percentages. Returns None when the
    inputs are degenerate (a 100% dairy feedlot has no beef-only share to speak
    of, and a stream heifer-rich enough to drive the remainder negative means the
    assumption is wrong rather than the market).
    """
    s, d, h = share_pct / 100.0, dairy_share_pct / 100.0, heifer_frac_pct / 100.0
    if d >= 1.0:
        return None
    adj = (s - h * d) / (1.0 - d)
    return 100.0 * adj if 0.0 <= adj <= 1.0 else None


def implied_dairy_share(share_now_pct, target_pct, heifer_frac_pct):
    """
    The d that would make the adjusted current reading equal `target_pct`.

    Rearranged from adjust():  d = (s - target) / (h_d - target)

    Used to ask what dairy-origin share would reconcile the feedlot decline with
    the sale-barn one. Returns None when no share in (0, 1) does it -- which is a
    real answer, not a failure: it means mix cannot explain the gap and the
    remainder is timing, or something neither series is showing.
    """
    s, t, h = share_now_pct / 100.0, target_pct / 100.0, heifer_frac_pct / 100.0
    if abs(h - t) < 1e-9:
        return None
    d = (s - t) / (h - t)
    return 100.0 * d if 0.0 < d < 1.0 else None
