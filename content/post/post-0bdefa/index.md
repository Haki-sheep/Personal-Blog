---
title: 输入系统
date: 2026-07-17T13:15:55+08:00
slug: post-0bdefa
categories:
    - ue
subcategories:
    - basic
---

Ue的新输入系统 (Enhanced)
架构和Unity非常相似

## Input Aciton 负责定有哪些操作行为
值类型: 数据类型
触发器:触发类型 比如长按 点按等
修改器:对该类型做处理 比如取模 去反等

![](Pasted-image-20260521071752.png "398")

## Input Map Context 操作配置表
相当于将具体的按键和Action绑定 以达成 "可复用" 抽象行为这一能力

![](Pasted-image-20260521072122.png "467")
