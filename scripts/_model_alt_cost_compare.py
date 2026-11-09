models = {
    "gemini-3.5-flash-lite (current)": (0.30, 2.50),
    "gemini-3.8-flash (intro thru 2026-12-31)": (0.75, 3.75),
    "gemini-3.6-flash (same intro rates)": (0.75, 3.75),
    "gemini-3.1-flash-lite": (0.25, 1.50),
}
in_low, in_high = 12000, 21000
out_cap = 4096
print(f"{'model':42} {'low':>10} {'high4k':>10} {'hi4096':>10} {'<=0.05'}")
for name, (iin, oout) in models.items():
    low = (in_low / 1e6) * iin + (1500 / 1e6) * oout
    high = (in_high / 1e6) * iin + (4000 / 1e6) * oout
    hcap = (in_high / 1e6) * iin + (out_cap / 1e6) * oout
    print(f"{name:42} {low:10.5f} {high:10.5f} {hcap:10.5f} {hcap <= 0.05}")
