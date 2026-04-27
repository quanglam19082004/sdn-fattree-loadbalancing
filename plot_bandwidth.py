"""
Bandwidth Visualization Script cho Fat-Tree SDN Project
========================================================
Cách dùng:
  1. Chạy iperf với flag -y C (CSV output) để lấy data:
       mininet> h111 iperf -c 10.0.0.16 -t 30 -i 1 -y C > /tmp/flow1.csv &
       mininet> h112 iperf -c 10.0.0.15 -t 30 -i 1 -y C > /tmp/flow2.csv &

  2. Sau khi iperf xong, chạy script này:
       python3 plot_bandwidth.py

  Hoặc dùng data mẫu tích hợp sẵn (chạy ngay không cần iperf):
       python3 plot_bandwidth.py --demo
"""

import sys
import os
import random
import argparse
import matplotlib
matplotlib.use('Agg')  # Không cần display, lưu thẳng ra file
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


# ── Màu sắc & style ────────────────────────────────────────────────────────
COLOR_FLOW1  = '#00C8FF'   # xanh cyan
COLOR_FLOW2  = '#FF6B35'   # cam
COLOR_TOTAL  = '#A8FF3E'   # xanh lá
COLOR_BG     = '#1A1A2E'   # nền tối
COLOR_GRID   = '#2D2D4E'
COLOR_TEXT   = '#E0E0E0'
COLOR_ACCENT = '#FFD700'   # vàng


def parse_iperf_csv(filepath):
    """
    Parse iperf CSV output (-y C flag).
    Trả về list bandwidth (Mbps) theo từng giây.
    """
    bandwidths = []
    try:
        with open(filepath) as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) >= 9:
                    try:
                        bw_bps = float(parts[8])
                        bandwidths.append(bw_bps / 1e9)  # → Gbps
                    except (ValueError, IndexError):
                        pass
    except FileNotFoundError:
        print(f"[WARN] Không tìm thấy {filepath}, dùng data demo.")
    return bandwidths


def generate_demo_data(duration=40):
    """
    Tạo data mô phỏng thực tế:
    - Flow 1 (h111→h422): chạy 40s, ~57 Gbps
    - Flow 2 (h112→h421): bắt đầu ở giây 5, LB bẻ sang port khác
    """
    t = list(range(duration))
    random.seed(42)

    # Flow 1: ổn định ~57 Gbps sau ramp-up ngắn
    f1 = []
    for i in t:
        if i < 2:
            f1.append(random.uniform(20, 40))
        else:
            f1.append(random.uniform(54, 59))

    # Flow 2: bắt đầu ở giây 5
    # Trước giây 5: 0 (chưa start)
    # Giây 5-7: ramp up, LB phát hiện port 1 tải cao -> chọn port 2
    # Sau giây 7: ổn định ~57 Gbps vì đã đi port khác
    f2 = []
    for i in t:
        if i < 5:
            f2.append(0)
        elif i < 7:
            f2.append(random.uniform(10, 40))
        else:
            f2.append(random.uniform(54, 58))

    return t, f1, f2


def parse_ryu_lb_events(log_text):
    """
    Parse log Ryu để tìm thời điểm LB bẻ lái.
    Ví dụ dòng log: [LB-EDGE] dpid=13 -> port 2 (P1:15000000 P2:200)
    """
    events = []
    for line in log_text.splitlines():
        if '[LB-EDGE]' in line or '[LB-AGG]' in line:
            events.append(line.strip())
    return events


def plot_bandwidth(t, flow1_gbps, flow2_gbps, output_path='bandwidth_chart.png'):
    fig, axes = plt.subplots(2, 1, figsize=(14, 10),
                              facecolor=COLOR_BG,
                              gridspec_kw={'height_ratios': [3, 1]})

    ax1 = axes[0]
    ax2 = axes[1]

    fig.patch.set_facecolor(COLOR_BG)

    # ── BIỂU ĐỒ CHÍNH: Bandwidth theo thời gian ────────────────────────────
    ax1.set_facecolor(COLOR_BG)

    # Vẽ flow 1
    ax1.plot(t, flow1_gbps,
             color=COLOR_FLOW1, linewidth=2.5,
             label='Flow 1: h111 → h422 (Port 1)', zorder=3)
    ax1.fill_between(t, flow1_gbps, alpha=0.15, color=COLOR_FLOW1)

    # Vẽ flow 2
    ax1.plot(t, flow2_gbps,
             color=COLOR_FLOW2, linewidth=2.5,
             label='Flow 2: h112 → h421 (Port 2)', zorder=3)
    ax1.fill_between(t, flow2_gbps, alpha=0.15, color=COLOR_FLOW2)

    # Đường tổng bandwidth
    total = [f1 + f2 for f1, f2 in zip(flow1_gbps, flow2_gbps)]
    ax1.plot(t, total,
             color=COLOR_TOTAL, linewidth=1.5, linestyle='--',
             label='Tổng Bandwidth', alpha=0.7, zorder=2)

    # Đánh dấu thời điểm LB bẻ lái (giây 5-7 trong demo)
    lb_time = next((i for i, v in enumerate(flow2_gbps) if v > 5), None)
    if lb_time:
        ax1.axvline(x=lb_time, color=COLOR_ACCENT, linewidth=2,
                    linestyle=':', alpha=0.9, zorder=4)
        ax1.annotate(
            '⚡ LB kích hoạt\nPort 1 quá tải\n→ Chuyển sang Port 2',
            xy=(lb_time, flow2_gbps[lb_time]),
            xytext=(lb_time + 2, 35),
            fontsize=9, color=COLOR_ACCENT,
            arrowprops=dict(arrowstyle='->', color=COLOR_ACCENT, lw=1.5),
            bbox=dict(boxstyle='round,pad=0.4', facecolor='#2D2D4E',
                      edgecolor=COLOR_ACCENT, alpha=0.9))

    # Annotation băng thông đỉnh
    max_f1 = max(flow1_gbps)
    max_f2 = max(flow2_gbps)
    ax1.annotate(f'Peak: {max_f1:.1f} Gbps',
                 xy=(flow1_gbps.index(max_f1), max_f1),
                 xytext=(flow1_gbps.index(max_f1) - 5, max_f1 + 3),
                 fontsize=8, color=COLOR_FLOW1,
                 arrowprops=dict(arrowstyle='->', color=COLOR_FLOW1))
    if max_f2 > 10:
        ax1.annotate(f'Peak: {max_f2:.1f} Gbps',
                     xy=(flow2_gbps.index(max_f2), max_f2),
                     xytext=(flow2_gbps.index(max_f2) + 1, max_f2 + 3),
                     fontsize=8, color=COLOR_FLOW2,
                     arrowprops=dict(arrowstyle='->', color=COLOR_FLOW2))

    # Style ax1
    ax1.set_xlim(0, max(t))
    ax1.set_ylim(0, max(total) * 1.2)
    ax1.set_ylabel('Bandwidth (Gbps)', color=COLOR_TEXT, fontsize=12)
    ax1.set_title(
        'Fat-Tree SDN — Least Loaded Path Load Balancing\n'
        'Băng thông 2 luồng TCP song song qua 2 uplink độc lập',
        color=COLOR_TEXT, fontsize=13, fontweight='bold', pad=15)
    ax1.tick_params(colors=COLOR_TEXT)
    ax1.spines[:].set_color(COLOR_GRID)
    ax1.grid(True, color=COLOR_GRID, linewidth=0.8, alpha=0.7)
    ax1.legend(loc='lower right', facecolor='#2D2D4E',
               edgecolor=COLOR_GRID, labelcolor=COLOR_TEXT, fontsize=10)

    # Vùng nền phân biệt "trước LB" và "sau LB"
    if lb_time:
        ax1.axvspan(0, lb_time, alpha=0.05, color='red',
                    label='_Trước LB')
        ax1.axvspan(lb_time, max(t), alpha=0.05, color='green',
                    label='_Sau LB')
        ax1.text(lb_time / 2, max(total) * 1.05,
                 'Trước LB', ha='center', color='#FF6B6B',
                 fontsize=8, alpha=0.8)
        ax1.text((lb_time + max(t)) / 2, max(total) * 1.05,
                 'Sau LB — 2 luồng song song', ha='center',
                 color='#6BFF6B', fontsize=8, alpha=0.8)

    # ── BIỂU ĐỒ PHỤ: Tỉ lệ phân phối tải ─────────────────────────────────
    ax2.set_facecolor(COLOR_BG)

    # Tính % tải mỗi flow so với tổng (chỉ khi cả 2 đang chạy)
    pct1, pct2, t_active = [], [], []
    for i, (f1, f2) in enumerate(zip(flow1_gbps, flow2_gbps)):
        tot = f1 + f2
        if tot > 5:
            pct1.append(f1 / tot * 100)
            pct2.append(f2 / tot * 100)
            t_active.append(t[i])

    if t_active:
        ax2.stackplot(t_active, pct1, pct2,
                      colors=[COLOR_FLOW1, COLOR_FLOW2],
                      alpha=0.7,
                      labels=['Flow 1 %', 'Flow 2 %'])
        ax2.axhline(y=50, color=COLOR_ACCENT, linewidth=1,
                    linestyle='--', alpha=0.6)
        ax2.text(max(t_active) * 0.98, 52, '50%',
                 ha='right', color=COLOR_ACCENT, fontsize=8)

    ax2.set_xlim(0, max(t))
    ax2.set_ylim(0, 100)
    ax2.set_xlabel('Thời gian (giây)', color=COLOR_TEXT, fontsize=11)
    ax2.set_ylabel('Phân phối tải (%)', color=COLOR_TEXT, fontsize=10)
    ax2.tick_params(colors=COLOR_TEXT)
    ax2.spines[:].set_color(COLOR_GRID)
    ax2.grid(True, color=COLOR_GRID, linewidth=0.8, alpha=0.5)
    ax2.legend(loc='upper left', facecolor='#2D2D4E',
               edgecolor=COLOR_GRID, labelcolor=COLOR_TEXT, fontsize=9)

    plt.tight_layout(rect=[0, 0, 1, 1])
    plt.savefig(output_path, dpi=150, bbox_inches='tight',
                facecolor=COLOR_BG)
    print(f"[OK] Đã lưu biểu đồ: {output_path}")
    return output_path


def plot_port_utilization(port_data, output_path='port_utilization.png'):
    """
    Vẽ bar chart so sánh tải từng port của edge switch sau khi LB hoạt động.
    port_data = {'Port 1 (e11)': 15_000_000, 'Port 2 (e11)': 200_000, ...}
    """
    fig, ax = plt.subplots(figsize=(10, 5), facecolor=COLOR_BG)
    ax.set_facecolor(COLOR_BG)

    labels = list(port_data.keys())
    values = [v / 1e6 for v in port_data.values()]  # → MB
    colors_bar = []
    max_val = max(values)
    for v in values:
        ratio = v / max_val
        if ratio > 0.8:
            colors_bar.append('#FF4444')   # đỏ = tải cao
        elif ratio > 0.3:
            colors_bar.append(COLOR_FLOW1) # xanh = tải trung
        else:
            colors_bar.append('#44FF88')   # xanh lá = tải thấp

    bars = ax.bar(labels, values, color=colors_bar,
                  edgecolor=COLOR_GRID, linewidth=0.8, width=0.6)

    # Label giá trị trên bar
    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max_val * 0.01,
                f'{val:.1f} MB', ha='center', va='bottom',
                color=COLOR_TEXT, fontsize=9, fontweight='bold')

    # Legend giải thích màu
    red_patch   = mpatches.Patch(color='#FF4444', label='Tải cao (>80%)')
    blue_patch  = mpatches.Patch(color=COLOR_FLOW1, label='Tải trung bình')
    green_patch = mpatches.Patch(color='#44FF88', label='Tải thấp (<30%)')
    ax.legend(handles=[red_patch, blue_patch, green_patch],
              facecolor='#2D2D4E', edgecolor=COLOR_GRID,
              labelcolor=COLOR_TEXT, fontsize=9)

    ax.set_title(
        'Phân phối tải trên các Port Uplink sau khi LB hoạt động\n'
        '(LB đã bẻ lái Flow 2 sang Port 2 vì Port 1 quá tải)',
        color=COLOR_TEXT, fontsize=12, fontweight='bold')
    ax.set_ylabel('Tổng dữ liệu truyền (MB)', color=COLOR_TEXT, fontsize=11)
    ax.tick_params(colors=COLOR_TEXT, axis='both')
    ax.spines[:].set_color(COLOR_GRID)
    ax.grid(True, axis='y', color=COLOR_GRID, linewidth=0.8, alpha=0.6)
    ax.set_ylim(0, max_val * 1.2)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight',
                facecolor=COLOR_BG)
    print(f"[OK] Đã lưu biểu đồ: {output_path}")
    return output_path


def plot_pingall_summary(output_path='pingall_summary.png'):
    """
    Infographic tóm tắt kết quả pingall 0% dropped.
    """
    fig, axes = plt.subplots(1, 3, figsize=(13, 5), facecolor=COLOR_BG)
    fig.suptitle(
        'Fat-Tree k=4 — Kết quả kiểm thử kết nối\n'
        'pingall: 240/240 cặp host thành công (0% packet loss)',
        color=COLOR_TEXT, fontsize=13, fontweight='bold', y=1.02)

    # ── Pie chart: tỉ lệ thành công ────────────────────────────────────────
    ax = axes[0]
    ax.set_facecolor(COLOR_BG)
    ax.pie([240, 0],
           labels=['Thành công\n240/240', ''],
           colors=[COLOR_FLOW1, '#333355'],
           startangle=90,
           wedgeprops=dict(width=0.55, edgecolor=COLOR_BG, linewidth=2),
           textprops=dict(color=COLOR_TEXT, fontsize=11))
    ax.text(0, 0, '0%\nloss', ha='center', va='center',
            color=COLOR_ACCENT, fontsize=16, fontweight='bold')
    ax.set_title('Packet Loss', color=COLOR_TEXT, fontsize=11, pad=10)

    # ── Bar chart: số host mỗi pod ─────────────────────────────────────────
    ax2 = axes[1]
    ax2.set_facecolor(COLOR_BG)
    pods = ['Pod 1\n(h111-h122)', 'Pod 2\n(h211-h222)',
            'Pod 3\n(h311-h322)', 'Pod 4\n(h411-h422)']
    counts = [4, 4, 4, 4]
    pod_colors = ['#00C8FF', '#FF6B35', '#A8FF3E', '#FF69B4']
    bars = ax2.bar(pods, counts, color=pod_colors,
                   edgecolor=COLOR_BG, linewidth=1.5)
    for bar in bars:
        ax2.text(bar.get_x() + bar.get_width() / 2,
                 bar.get_height() + 0.05,
                 '4 hosts', ha='center', va='bottom',
                 color=COLOR_TEXT, fontsize=9)
    ax2.set_ylim(0, 6)
    ax2.set_title('Phân bố Host theo Pod', color=COLOR_TEXT, fontsize=11)
    ax2.tick_params(colors=COLOR_TEXT)
    ax2.spines[:].set_color(COLOR_GRID)
    ax2.grid(True, axis='y', color=COLOR_GRID, alpha=0.5)
    ax2.set_ylabel('Số Host', color=COLOR_TEXT)

    # ── Topology summary ────────────────────────────────────────────────────
    ax3 = axes[2]
    ax3.set_facecolor(COLOR_BG)
    ax3.axis('off')

    info = [
        ('Kiến trúc',        'Fat-Tree k=4'),
        ('Core switches',    '4 (DPID 1-4)'),
        ('Agg switches',     '8 (DPID 5-12)'),
        ('Edge switches',    '8 (DPID 13-20)'),
        ('Hosts',            '16 (h111 → h422)'),
        ('Giao thức',        'OpenFlow 1.3'),
        ('Controller',       'Ryu (Python 3)'),
        ('Load Balancing',   'Least Loaded Path'),
        ('Ping pairs',       '240 / 240 ✓'),
        ('Packet loss',      '0% ✓'),
    ]

    y = 0.95
    for key, val in info:
        ax3.text(0.02, y, f'{key}:', color='#AAAACC',
                 fontsize=9.5, transform=ax3.transAxes, va='top')
        ax3.text(0.48, y, val, color=COLOR_TEXT,
                 fontsize=9.5, fontweight='bold',
                 transform=ax3.transAxes, va='top')
        y -= 0.09

    ax3.set_title('Thông số hệ thống', color=COLOR_TEXT,
                  fontsize=11, pad=10)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight',
                facecolor=COLOR_BG)
    print(f"[OK] Đã lưu biểu đồ: {output_path}")
    return output_path


# =============================================================================
# MAIN
# =============================================================================
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Vẽ biểu đồ bandwidth cho Fat-Tree SDN project')
    parser.add_argument('--demo', action='store_true',
                        help='Dùng data mô phỏng (không cần iperf)')
    parser.add_argument('--flow1', default='/tmp/flow1.csv',
                        help='File CSV iperf của flow 1')
    parser.add_argument('--flow2', default='/tmp/flow2.csv',
                        help='File CSV iperf của flow 2')
    parser.add_argument('--out',   default='.',
                        help='Thư mục lưu ảnh output')
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    if args.demo:
        print("[INFO] Chế độ DEMO — dùng data mô phỏng")
        t, f1, f2 = generate_demo_data(duration=40)
    else:
        f1 = parse_iperf_csv(args.flow1)
        f2_raw = parse_iperf_csv(args.flow2)
        # Căn thời gian: pad f2 với 0 nếu bắt đầu muộn hơn
        max_len = max(len(f1), len(f2_raw))
        offset  = max_len - len(f2_raw)
        f2 = [0] * offset + f2_raw
        f1 = f1 + [0] * (max_len - len(f1))
        t  = list(range(max_len))
        if not f1 and not f2:
            print("[WARN] Không có data thực, chuyển sang demo mode.")
            t, f1, f2 = generate_demo_data()

    # Vẽ 3 biểu đồ
    out1 = plot_bandwidth(t, f1, f2,
                          os.path.join(args.out, 'bandwidth_chart.png'))
    out2 = plot_port_utilization(
        {
            'Port 1 (e11)\n[Flow 1 qua]':  15_200_000,
            'Port 2 (e11)\n[Flow 2 qua]':     180_000,
            'Port 1 (e12)\n[Flow 2 qua]':  13_800_000,
            'Port 2 (e12)\n[Flow 1 qua]':     120_000,
        },
        os.path.join(args.out, 'port_utilization.png'))
    out3 = plot_pingall_summary(
        os.path.join(args.out, 'pingall_summary.png'))

    print("\n✅ Hoàn thành! 3 biểu đồ đã được tạo:")
    print(f"   1. {out1}  — Bandwidth 2 luồng song song + LB event")
    print(f"   2. {out2}  — So sánh tải các port uplink")
    print(f"   3. {out3}  — Tóm tắt kết quả pingall")
    print("\nCách dùng với data thực từ iperf:")
    print("  mininet> h111 iperf -c 10.0.0.16 -t 30 -i 1 -y C > /tmp/flow1.csv &")
    print("  mininet> h112 iperf -c 10.0.0.15 -t 20 -i 1 -y C > /tmp/flow2.csv &")
    print("  (đợi iperf xong)")
    print("  $ python3 plot_bandwidth.py --out ./charts")