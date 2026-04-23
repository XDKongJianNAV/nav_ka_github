# Issue 03 Impact Matrix

| 问题项 | 教材金标准 | 对比口径 | 关键指标变化 | 解释 |
| --- | --- | --- | --- | --- |
| 运行时真值注入 | 环路只能由观测与内部状态驱动 | legacy -> issue01 | `tau` mean Δ = 3913.059, WLS mean Δ = 1543.994 | 去掉 truth stabilization 后，独立性恢复，低频脆弱区暴露。 |
| 信号层未真实包含导航数据 | data-bearing signal 必须真的进信号对象 | issue01 -> issue03 | `tau` mean Δ = 9584.076, `fd` mean Δ = 5721.196 | Issue 03 把 data bit 纳入接收块，前端性能变化开始反映真实 data-bearing channel。 |
| 自然测量量与标准观测混层 | observables 必须独立形成 | issue01 -> issue03 | WLS mean Δ = 2508.314, EKF pos mean Δ = 54314.189 | 导航层开始只消费 formal observables，解释资格恢复。 |
| 环路结构只剩工程控制律 | discriminator / filter / NCO 应可分离建模 | issue01 -> issue03 | `fd` mean Δ = 5721.196, EKF vel mean Δ = 4724.641 | 结构化 carrier/code loop 后，前端和动态层的耦合变化可被单独解释。 |
