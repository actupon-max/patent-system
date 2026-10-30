# samples/

真實案件放這裡（此資料夾內容不會進 git）。每案一個資料夾，內含說明書 `.docx` 與圖式 `.pdf`：

```
samples/
  case1/  第一案說明書.docx  第一案圖式.pdf
  case2/  第二案說明書.docx  第二案圖式.pdf
```

驗收：`PATENT_SAMPLES_DIR=samples python3 -m pytest tests/test_real_samples.py -v -s`
