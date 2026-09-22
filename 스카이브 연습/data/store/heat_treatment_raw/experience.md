# 열처리 공정 이상탐지 (개인 프로젝트)
> 열처리 공정의 이상 탐지를 위한 모델 개발

## Overview
- 유형: project
- 학년: 3학년
- 기간: 2025.09 ~ 2025.11
- 소속/유형: 확인 필요

## Problem
서서히 벗어나는 이상은 놓친다는 문제

## My Role
작성자 [근거: README.md @ L1-17]

## Action
- (본인) 공개 열처리 공정 온도 로그를 수집하고 정상/이상 구간을 직접 라벨링 [근거: README.md @ L1-17]
- (본인) 온도 변화율과 구간 편차를 특징으로 만들어 Isolation Forest로 이상 점수 산출 [근거: code/detect.py @ L1-19] [근거: code/detect.py @ L1-19]
- (본인) 규칙 기반 알람과 같은 데이터로 재현율 비교 [근거: README.md @ L1-17]

## Technical Decisions / Trial & Error
- 확인 필요

## Results
- (팀) 이상 구간 재현율: 규칙 기반 0.64 → 제안 방식 0.91 [근거: README.md @ L1-17]
- (팀) 오탐률은 규칙 기반과 비슷한 수준(둘 다 약 5%) [근거: README.md @ L1-17]

## Skills / Tools
numpy, sklearn, IsolationForest

## Lessons
확인 필요

## Evidence (원본 파일)
- README.md
- code/detect.py

## Open Questions (사용자 확인 필요)
- 이 프로젝트에서 배운 점이나 소감은 무엇인가요?
