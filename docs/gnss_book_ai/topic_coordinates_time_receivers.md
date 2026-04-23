# 坐标、时间与观测形成专题索引

这个文件不是正文转写，而是后续核对实现时的快速入口。页码均为 **PDF 页码**，对应的整页版式图在 `assets/page_renders/` 下。

## 1. 坐标定义

教材目录中的相关入口：

- `Reference Coordinate Systems`，PDF 第 `39` 页开始
- `Earth-Centered Inertial (ECI) Coordinate System`
- `Earth-Centered Earth-Fixed (ECEF) Coordinate System`
- `Local Tangent Plane (Local Level) Coordinate Systems`
- `Geodetic (Ellipsoidal) Coordinates`

建议优先查看的 PDF 页：

- `40` 到 `48`

对应页图：

- [page-0040.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0040.png)
- [page-0041.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0041.png)
- [page-0042.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0042.png)
- [page-0043.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0043.png)
- [page-0044.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0044.png)
- [page-0045.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0045.png)
- [page-0046.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0046.png)
- [page-0047.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0047.png)
- [page-0048.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0048.png)

这部分后续主要用于核对：

- 我们的 `lla_to_ecef`
- `ecef_to_enu_rotation_matrix`
- `ecef_delta_to_enu`
- 本地 ENU 与右手系约定
- 大地坐标、椭球高与本地切平面的定义是否一致

## 2. 时间与频率定义

教材目录中的相关入口：

- `Frequency Sources, Time, and GNSS`，PDF 第 `91` 页开始
- `Time and GNSS`

建议优先查看的 PDF 页：

- `91` 到 `95`

对应页图：

- [page-0091.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0091.png)
- [page-0092.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0092.png)
- [page-0093.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0093.png)
- [page-0094.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0094.png)
- [page-0095.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0095.png)

这部分后续主要用于核对：

- 系统时间、卫星钟差、接收机钟差的符号与基准
- 时间偏差如何进入伪距方程
- 我们当前代码里的 `receiver_clock_bias_m`、`receiver_clock_drift_mps` 是否只是“数值参数”，还是已经对应到标准时间定义

## 3. 接收机中的观测形成

教材目录中的相关入口：

- `GNSS Receivers`，PDF 第 `352` 页开始
- `Carrier Tracking`，PDF 第 `458` 页开始
- `Code Tracking`，PDF 第 `465` 页开始
- `Formation of Pseudorange, Delta Pseudorange, and Integrated  Doppler`，PDF 第 `508` 页开始

建议优先查看的 PDF 页：

- `508` 到 `512`

对应页图：

- [page-0508.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0508.png)
- [page-0509.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0509.png)
- [page-0510.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0510.png)
- [page-0511.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0511.png)
- [page-0512.png](/Users/guozehao/Documents/ka-Nav/nav_ka_github/docs/gnss_book_ai/assets/page_renders/page-0512.png)

这部分后续主要用于核对：

- 码相位、载波相位、Doppler 与标准观测量之间的映射
- `pseudorange`
- `delta pseudorange`
- `integrated Doppler`
- 我们当前把 DLL/PLL 内部量映射到导航观测层时是否缺少标准定义步骤

## 4. 和当前实现的直接对应

当前最需要对照的实现位置：

- [exp_multisat_wls_pvt_report.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/notebooks/exp_multisat_wls_pvt_report.py)
- [exp_dynamic_multisat_ekf_report.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/notebooks/exp_dynamic_multisat_ekf_report.py)
- [nb_ka225_rx_from_real_wkb_debug.py](/Users/guozehao/Documents/ka-Nav/nav_ka_github/notebooks/nb_ka225_rx_from_real_wkb_debug.py)

建议下一步检查顺序：

1. 先对照坐标定义，确认 `LLA -> ECEF -> ENU` 和 LOS 方向约定。
2. 再对照时间定义，确认钟差、钟漂和观测时间基准。
3. 最后再回到接收机章节，核对 `pseudorange / Doppler / carrier phase` 的形成过程。
