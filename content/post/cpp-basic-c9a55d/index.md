---
title: Cpp数据结构
date: 2026-07-17T13:15:27+08:00
slug: cpp-basic-c9a55d
categories:
    - cpp
subcategories:
    - basic
---

# 1.枚举
# 2.数组
## 栈数组
1.栈数组长度必须是**编译期常量** 不能用运行时变量  
比如  int a = 10; int array[a];  标准 C++ 不能通过（这是变长数组扩展）  
可以： int array[10];  或  constexpr int n = 10; int array[n]; 

2.栈数组没有原生长度等方法  
只能  length = sizeof(array)/sizeof(array[0]) （或者 sizeof 其类型）

3.栈数组在函数传递的时候会退化成指针 就不会拿到我们想要的长度信息了

![](Pasted-image-20260711101131.png "462")

## 堆数组


# 3.结构体
# 4.链表
# 5.树
# 6.哈希Map
