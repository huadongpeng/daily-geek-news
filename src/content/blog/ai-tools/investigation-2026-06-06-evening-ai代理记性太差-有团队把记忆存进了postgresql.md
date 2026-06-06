---
title: "AI代理记性太差？有团队把记忆存进了PostgreSQL"
date: 2026-06-06T18:00:00+08:00
updated: 2026-06-06T18:46:27+08:00
categories: ["ai-tools"]
tags: ["深度调查", "evening"]
wordCount: 749
draft: false
description: "Databricks用托管PostgreSQL实现AI代理的状态持久化，打破向量数据库依赖。思路实用但学习门槛不低，适合有LangGraph基础的技术人尝试。"
cover: "/images/covers/investigation-2026-06-06-evening-ai代理记性太差-有团队把记忆存进了postgresql.jpg"
sources:
  - name: "DEV Community - AI Agent Memory Management: Beyond the Context Window"
    url: "https://dev.to/mudassirworks/ai-agent-memory-management-beyond-the-context-window-5c65"
  - name: "Microsoft pg_durable"
    url: "https://github.com/microsoft/pg_durable"
---

今天下午修一个自动化脚本，被AI气笑了。

我给代理布置了三步任务：先爬商品价格，再对比库存，最后生成调货建议。第一步跑完，到第二步它开始胡编价格——明显是把第一步输出丢了。

这感觉搞技术的都明白：东西能用，但半路掉链子。

我停下来喝了口水，脑子里冒出一个问题：有没有不贵的办法，让代理记住上下文？

随手打开搜索，打了几个关键词。结果第三条就把我吸引了——Databricks发布了一套“AI Agent Memory”方案。

点进去看了一会儿，我忍不住笑了：方案的核心，是PostgreSQL。

没逗你，就是那个咱用了二十年的关系数据库。

只不过披了个“Lakebase”的马甲，全托管，兼容Postgres。

他们怎么玩的？

利用LangGraph的checkpointing机制，把代理每步的状态序列化存进Postgres。这样不管是会话超时、服务重启，还是跨多轮对话，状态都能恢复。

我看了一眼官方模板——几个文件，三百行代码，就把记账、断点续跑、后台守护全包了。

说人话就是：让AI代理像玩游戏存档一样，任何一步都能“读盘重来”。

这思路不新，但实用到让人拍大腿。

过去搞Agent记忆，要么用向量数据库存知识，要么靠外挂工具。效果好不好另说，但光运维成本就劝退个人开发者。

Postgres的方案，直接把成本砸下来了。一台低配RDS，月费几十块，就能撑起一个轻量级代理的“海马体”。

当然，不是没门槛。

我翻了他们的模板代码，发现前提条件是：你得熟悉LangGraph，还得懂异步、checkpoint序列化这些。

对于一个没摸过状态图的普通后端，学习曲线不低。

另外，Databricks这方案绑在他们云上，如果你用的是其他云或者自建机器，得想办法移植。

还有个开源项目叫pg_durable，看起来也想做类似的事，但README写得太简略，我没敢深交。

我现在的判断是：思路可以学，但立刻上生产要慎重。

周末我打算把Databricks的模板clone下来，用免费额度跑一次。就做一件事：让代理连续五步不丢记忆。

如果跑得通，那下次做自动化工具，就可以拿这套架构改了。

兄弟们也可以试试，但要小心两件事：

一，别一上来就买服务，先用本地Postgres模拟。二，如果你的场景不需要多步记忆，就别套这层复杂度。

说到底，AI代理缺的不是智商，是记性。而记性问题的答案，可能就藏在一张我们非常熟悉的表里。

以上。

既然看到这里了，觉得有点用的话，点个赞或者转发一下，让更多朋友看到。

我们下次再聊。

老花 / Easton Hua
