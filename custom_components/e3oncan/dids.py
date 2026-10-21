"""Data points polled per controller in read mode: DID -> interval in seconds.

The selection mirrors the read-only sensors of open3e-ha
(https://github.com/MojoOli/open3e-ha), so switching from it loses nothing.
DIDs an ECU does not support are detected on the first poll and then skipped.
"""

# Values that change quickly (power, compressor, valve, fans): every 10 s.
# Everything else that open3e-ha reads every 5 s (temperatures): every 30 s.
FAST = 10
SLOW = 30
_VITOCAL_FAST = {1190, 1775, 1776, 2346, 2351, 2352, 2486, 2487, 2488, 2496, 2569, 2735, 2791, 2806}
_VITOAIR_FAST = {1040, 1041}

VITOCAL_DIDS: dict[int, int] = {
    268: 5, 269: 5, 271: 5, 274: 5, 284: 5, 286: 5, 288: 5, 290: 5, 318: 15, 320: 5,
    321: 5, 322: 15, 324: 5, 325: 15, 334: 5, 335: 5, 336: 5, 337: 5, 355: 5, 381: 10,
    389: 30, 391: 30, 396: 300, 401: 10, 402: 10, 403: 10, 404: 10, 475: 30, 476: 30,
    477: 30, 478: 30, 497: 30, 543: 30, 548: 300, 565: 300, 566: 300, 627: 86400,
    628: 86400, 629: 86400, 630: 86400, 873: 60, 987: 30, 988: 30, 989: 30, 990: 30,
    1043: 30, 1101: 300, 1192: 300, 1193: 300, 1211: 30, 1391: 30, 1643: 30, 1644: 30,
    1721: 3600, 1731: 30, 1769: 5, 1771: 30, 1772: 30, 1775: 5, 1776: 5, 2256: 30,
    2320: 30, 2333: 30, 2334: 30, 2346: 10, 2350: 30, 2351: 30, 2352: 30, 2369: 120,
    2370: 120, 2442: 300, 2486: 5, 2487: 5, 2488: 5, 2496: 5, 2529: 30, 2544: 300,
    2545: 300, 2560: 300, 2569: 10, 2622: 300, 2623: 300, 2624: 300, 2625: 300,
    2629: 30, 2630: 300, 2634: 300, 2735: 30, 2791: 10, 2792: 10, 2793: 10, 2806: 10,
    2855: 30, 2856: 300, 3016: 30, 3017: 30, 3018: 30, 3170: 300, 3232: 30, 3233: 30,
    3234: 30,
    # generated heat / energy today, also used for COP
    1190: 10,
}

VITOAIR_DIDS: dict[int, int] = {
    327: 5, 328: 5, 329: 5, 330: 5, 419: 5, 420: 5, 421: 5, 422: 5, 439: 30, 533: 30,
    1040: 10, 1041: 10, 1088: 30, 1089: 30, 2247: 300, 2248: 30, 2328: 10, 2355: 300,
    2403: 30, 2489: 30, 2493: 30, 2760: 300, 2797: 30, 3206: 300,
}


def _tune(dids: dict[int, int], fast: set[int]) -> dict[int, int]:
    return {did: FAST if did in fast else (SLOW if sec < SLOW else sec) for did, sec in dids.items()}


VITOCAL_DIDS = _tune(VITOCAL_DIDS, _VITOCAL_FAST)
VITOAIR_DIDS = _tune(VITOAIR_DIDS, _VITOAIR_FAST)
