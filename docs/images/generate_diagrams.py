"""Generate architecture and workflow diagrams for the README."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

# ─── ARCHITECTURE DIAGRAM ─────────────────────────────────────────────────────

def draw_arch():
    fig, ax = plt.subplots(figsize=(14, 9))
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 9)
    ax.axis("off")
    fig.patch.set_facecolor("#0F1117")
    ax.set_facecolor("#0F1117")

    def box(x, y, w, h, color, label, sublabel=None, radius=0.3):
        rect = FancyBboxPatch((x, y), w, h,
                              boxstyle=f"round,pad=0.05,rounding_size={radius}",
                              facecolor=color, edgecolor="white", linewidth=0.8, alpha=0.92)
        ax.add_patch(rect)
        cy = y + h / 2 + (0.12 if sublabel else 0)
        ax.text(x + w / 2, cy, label, ha="center", va="center",
                fontsize=9, fontweight="bold", color="white")
        if sublabel:
            ax.text(x + w / 2, y + h / 2 - 0.18, sublabel, ha="center", va="center",
                    fontsize=7, color="#CCCCCC")

    def arrow(x1, y1, x2, y2):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color="#4C9BE8",
                                   lw=1.5, mutation_scale=14))

    def label(x, y, txt, size=7.5, color="#AAAAAA"):
        ax.text(x, y, txt, ha="center", va="center", fontsize=size, color=color)

    # Title
    ax.text(7, 8.65, "Automated Sales Analytics Copilot — Architecture",
            ha="center", va="center", fontsize=13, fontweight="bold", color="white")

    # Row 1 — Data source
    box(5.5, 7.5, 3, 0.7, "#2C3E50", "Superstore CSV", "data/raw/Superstore.csv")

    # Row 2 — Phase 1
    box(4.5, 6.3, 5, 0.8, "#1A5276", "Phase 1 — ETL Pipeline", "ingest.py · 9,986 rows loaded")
    arrow(7, 7.5, 7, 7.1)

    # Row 3 — Phase 2
    box(4.5, 5.1, 5, 0.8, "#1A5276", "Phase 2 — PostgreSQL Star Schema", "5 KPI Views · fact_sales · 4 dims")
    arrow(7, 6.3, 7, 5.9)

    # Row 4 — Phase 3 (two boxes side by side)
    box(3.0, 3.85, 3.5, 0.85, "#1F618D", "Phase 3a — Anomaly Detection", "4 rules · 20 anomalies found")
    box(7.5, 3.85, 3.5, 0.85, "#1F618D", "Phase 3b — Forecasting", "Prophet + ARIMA · 80% CI")
    arrow(6.0, 5.1, 4.75, 4.7)
    arrow(8.0, 5.1, 9.25, 4.7)

    # Row 5 — Phase 4
    box(4.5, 2.7, 5, 0.8, "#1A5276", "Phase 4 — Tool Layer", "6 tools · dispatch_tool · TOOL_DEFINITIONS")
    arrow(4.75, 3.85, 5.8, 3.5)
    arrow(9.25, 3.85, 8.2, 3.5)

    # Row 6 — Phase 5
    box(4.5, 1.55, 5, 0.8, "#6C3483", "Phase 5 — Agentic Claude Loop", "claude-sonnet-4-6 · multi-step tool calling")
    arrow(7, 2.7, 7, 2.35)

    # Row 7 — outputs (three boxes)
    box(1.2, 0.3, 3.2, 0.85, "#117A65", "Phase 6", "Streamlit Chat UI")
    box(5.4, 0.3, 3.2, 0.85, "#117A65", "Phase 7", "GitHub Actions + Alerts")
    box(9.6, 0.3, 3.2, 0.85, "#117A65", "Phase 8", "Power BI / Tableau")
    arrow(5.8, 1.55, 2.8, 1.15)
    arrow(7.0, 1.55, 7.0, 1.15)
    arrow(8.2, 1.55, 11.2, 1.15)

    plt.tight_layout(pad=0.3)
    plt.savefig("docs/images/architecture.png", dpi=150, bbox_inches="tight",
                facecolor="#0F1117")
    plt.close()
    print("Saved docs/images/architecture.png")


if __name__ == "__main__":
    draw_arch()
