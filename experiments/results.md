| 방식 | 동시 요청 | 결과 | 대기 메모리 | 최대 메모리 | 전체 소요 |
|---|---|---|---|---|---|
| naive | 1건 | all done ✅ | 63MiB | 422MiB | 34.3초 |
| naive | 3건 | OOM Killed 💥 | 63MiB | 512MiB | 101.5초 |
| queue | 1건 | all done ✅ | 38MiB | 46MiB | 14.3초 |
| queue | 3건 | all done ✅ | 37MiB | 47MiB | 39.3초 |
| queue | 5건 | all done ✅ | 38MiB | 47MiB | 58.4초 |
| queue | 10건 | all done ✅ | 38MiB | 48MiB | 114.5초 |
