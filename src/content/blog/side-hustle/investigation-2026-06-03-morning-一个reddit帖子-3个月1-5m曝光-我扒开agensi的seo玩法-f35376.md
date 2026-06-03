---
title: "一个Reddit帖子，3个月1.5M曝光：我扒开Agensi的SEO玩法后，发现这事确实有点意思"
date: 2026-06-03T06:00:00+08:00
updated: 2026-06-03T10:27:52+08:00
categories: ["side-hustle"]
tags: ["深度调查", "morning"]
wordCount: 1537
draft: false
description: "非技术创始人靠Claude和结构化数据做AI技能市场，3个月获得150万曝光。我拆解了背后的“技能即内容”飞轮和面向AI搜索引擎的优化策略，发现普通人也能低成本复制单点技能页面。"
cover: "/images/covers/investigation-2026-06-03-morning-一个reddit帖子-3个月1-5m曝光-我扒开agensi的seo玩法-f35376.jpg"
sources:
  - name: "Reddit r/SaaS 原帖"
    url: "https://www.reddit.com/r/SaaS/comments/1tukbxt/15m_impressions_129k_clicks_in_3_months_my_entire/"
  - name: "Agensi.io"
    url: "https://agensi.io"
  - name: "Claude SEO Skill 官网"
    url: "https://claudeseoskill.com"
  - name: "GitHub claude-seo 仓库"
    url: "https://github.com/AgriCiDaniel/claude-seo"
---

昨天下午，我在河马奥莱排队结账，刷Reddit看到一篇帖子：“1.5 million impressions, 129k clicks in 3 months. My entire SEO strategy for Agensi.io”。

我愣了一秒，1.5M曝光，一个非技术创始人做的AI代理技能市场？这数字是真的吗？我差点把一瓶白酒放回去，打开手机仔细看。

帖子不长，但写得挺实在。没有卖课链接，只说了用Claude生成内容，做了结构化数据。我当时的感觉很奇怪——不是那种“哇好厉害”的仰望，是一种“这他妈怎么跟我想的完全不一样”的短路。因为我也是程序员，知道1.5M曝光意味着什么，
但他是非技术背景，凭什么？

所以我没结账，靠在购物车边上，开始顺着这条线查下去。

## 这数字靠谱吗？我先查源码和同类站
打开agensi.io，右键“查看页面源代码”。第一眼就看到了Schema.org结构化数据：`@type: SoftwareApplication`，带着应用名称、描述、价格（有的标0）。这玩意儿是给搜索引擎看的，能让结果展示得更丰富，
但一般小站点不太会搞。他一个非技术创始人，怎么会上来就这么专业？

接着我搜“agensi claude seo”，跳出来一个claudeseoskill.com。点进去，发现这个站几乎就是SEO教科书级别的范例：同样有Schema.org标记，还多了FAQPage结构化数据，
内容针对“AI-powered SEO, GEO & AEO Audits”这种长尾词。更绝的是，页面里直接放了Quick Audit和Full Audit的入口——这哪是卖技能，这分明是把产品本身做成了流量入口。

我又去GitHub搜了“claude-seo”，果然有一个仓库AgriCiDaniel/claude-seo，里面25个子技能、18个子代理，全是给Claude用的SEO工具模块。仓库的README写得清晰，甚至有安装指南。
这下我有点明白了：这很可能不是Agensi官方的东西，但却是生态的一部分——如果平台上的技能都按这个思路搞SEO，那整个平台的流量就不是一个站，而是一张网。

## 不是传统外链，是“技能即内容”的飞轮
这时候我回过味来。Agensi玩的不是传统SEO那一套——它不是靠外链、靠站群，而是靠“技能即内容”。每个技能页面，比如“AI Search Optimizer”，本身就针对一个具体需求做了关键词优化。
用户在Google里搜“Claude SEO audit”，可能先命中claudeseoskill.com，然后从那里再导流到Agensi。这就是飞轮：技能越多，长尾词覆盖越多，流量越大；流量越大，越有开发者愿意上传技能；技能越多，
又覆盖更多长尾词。

更让我警惕的是，他们大量用结构化数据。这东西不光帮传统搜索引擎，现在AI搜索引擎（比如Perplexity、Google的AI概览）也会优先读取结构化数据，直接抓来回答用户问题。等于说，Agensi是在给未来的AI搜索做“卡片优化”，
等AI搜索全面普及，他可能比竞争对手早半拍被引用。

查到这里，我感觉这个案例至少有三成是真的。为什么不是七成？因为1.5M曝光这个数字只有那个Reddit帖子和一条被污染的推文，没有第三方工具验证。我拿SimilarWeb免费版查了一下，
Agensi的月访问量估计在10万-50万之间（免费版数据很糙），和1.5M曝光如果按点击率10%算的话差不多，但毕竟不是直接数据。所以这个数字我暂时打五折信。

## 这玩法普通人能不能复制？
先拆机。这不算垃圾局——他没卖课，没让你加群，没承诺月入多少，他只是分享了个策略。也不像脏机会，虽然有点SEO技术流，但没擦边。

老花我自己能试吗？坦率地讲，我现在试不了。不是我不信这个路子，是我没那个时间维护一个技能市场平台。就算只做一个单技能页面，比如“Claude代码审查技能”，从写代码、做页面、做结构化数据到内容优化，少说要两周（我还是下班后挤时间）。
而且最关键的是，流量的冷启动需要耐心，我现在的状态等不起。

但兄弟可冲。如果你是个用Claude的开发者，手里正好有一两个趁手的提示词或者工作流，完全可以把它们打包成技能页面。你不需要做整个市场，就做单点。去GitHub Pages或者最简单的静态站，
按claudeseoskill.com的模板抄一份结构化数据，针对一个长尾词写一篇东西，然后挂到Agensi或者自己推。

第一步就是今天：打开claudeseoskill.com，右键查看源码，复制他家的Schema.org标记，改一下名字和描述。成本0元，耗时1小时。用Google的Rich Results Test验证通过，就算入门。
停止信号也很明确：如果连续两周，Google Search Console显示这个页面连10个点击都没有，或者目标词还没进前50，就先别优化其他页面，回头检查是不是关键词选错了或者竞争太激烈。

至于我，我暂时看戏。但我会盯着Agensi接下来几个月的动作：技能数量是不是每月涨20%以上？有没有付费技能出现？第三方媒体报道多不多？如果这些信号都绿了，说明这个模式的生命力被市场验证过一遍了。那时候我再下场，可能还有汤喝。

写到这儿我又想起开头在河马奥莱排队的场景。那个Reddit帖子就像一面镜子，照出了我这类人的一种惯性：总觉得要做就得整个大的，平台啊、生态啊，结果一直停在“研究完但还没开始”。而人家非技术创始人，抓一个单点，一个月内上线，三个月出数据。
这之间的差距，真不是差在技术。

以上。

既然看到这里了，觉得有点用的话，点个赞或者转发一下，让更多朋友看到。

我们下次再聊。

老花 / Easton Hua
