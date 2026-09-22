# 건설장비 유압 시스템 PHM 데이터 분석
> 굴착기 유압 시스템의 압력·온도 센서 로그로 고장 징후를 사전에 찾는 프로젝트.

## Overview
- 유형: project
- 학년: 2학년
- 기간: 2024.03 ~ 2024.06
- 소속/유형: 교내 산학 과제

## Problem
굴착기 유압 시스템의 고장 징후를 사전에 찾는 것

## My Role
작성자 [근거: README.md @ L1-18]

## Action
- (본인) 가동 상태를 구분하지 않고 전체 데이터에 하나의 임계값을 적용했더니 정상 구간에서 오탐이 많았다. [근거: analysis_notes.md @ L1-13]
- (본인) 엔진 회전수와 유압 펌프 부하로 공회전/굴착/이동 세 가지 상태를 구분하는 규칙을 정의했다. [근거: analysis_notes.md @ L1-13]
- (팀) 상태별로 나눠서 학습하자 F1-score가 0.62에서 0.78로 올랐다. [근거: README.md @ L1-18]
- (본인) 라벨링 규칙 v1은 압력 상승만 봤는데, 실제 고장 전에는 온도 상승이 압력보다 늦게 나타난다는 것을 발견했다. [근거: analysis_notes.md @ L1-13]
- (본인) v2에서는 온도 지연을 함께 고려하도록 수정했다. [근거: analysis_notes.md @ L1-13]

## Technical Decisions / Trial & Error
- (본인) 가동 상태를 구분하지 않고 전체 데이터에 하나의 임계값을 적용했더니 정상 구간에서 오탐이 많았다. [근거: analysis_notes.md @ L1-13]
- (팀) 상태별로 나눠서 학습하자 F1-score가 0.62에서 0.78로 올랐다. [근거: README.md @ L1-18]

## Results
- (팀) 이상 탐지 F1-score가 0.62에서 0.78로 향상됨 [근거: README.md @ L1-18]

## Skills / Tools
EDA, LSTM, Python

## Lessons
확인 필요

## Evidence (원본 파일)
- README.md
- analysis_notes.md
- results.csv

## Open Questions (사용자 확인 필요)
- 프로젝트에서 배운 점이나 소감은 무엇인가요?
