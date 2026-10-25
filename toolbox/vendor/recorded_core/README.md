# GNSS118_A_ENGINEERING_BASELINE_RC1

本包用于A路线工程基线的本地保存和内部移交。默认路径为原UrbanNav GPS C1C连续窗口→同日NAV→标准SPP/SPP_FDE→E2五项资格；历史比较默认关闭。它包含当前实际源码，未要求存在Git仓库或原开发工作树。

## 1. 外部输入和环境

需要三份包外文件，大小和SHA256见`EXTERNAL_DEPENDENCIES.json`：原后部F9P splitter OBS、2021-05-17/DOY137 NAV、原Windows RTKLIB包装DLL。本包不含原OBS/NAV/DLL、Python环境或真实观测测试摘录；不自动下载文件。提供者和许可状态一并登记，当前范围为内部移交，未取得任意公开再分发许可的条目标记UNKNOWN。

本机已验证环境是64位Windows、Python3.13.5、NumPy2.1.3，测试使用pytest8.3.4，可直接复用`E:/GNSS-Geo/.local/references/step39-raw-l1c/venv/Scripts/python.exe`。标准库及第三方库来自该环境，第一方代码从本解压目录加载。未验证其他设备、系统或Python版本；本轮不安装环境。

## 2. 建立本地配置

在解压后的本目录打开终端，修改下面命令的Python、OBS、NAV、DLL及输出根目录。输出目录必须在包外，并且不能位于外部数据目录内；配置文件使用一个尚未存在的新名称。

```powershell
& 'E:/GNSS-Geo/.local/references/step39-raw-l1c/venv/Scripts/python.exe' -I -B -X utf8 tools/experiments/prepare_baseline_config.py --obs 'E:/GNSS-Geo/datasets/urbannav/hk_medium/raw/gnss/UrbanNav-HK-Medium-Urban-1.ublox.f9p.splitter.obs' --nav 'E:/GNSS-Geo/datasets/ephemeris/2021/137/BRDM00DLR_S_20211370000_01D_MN.rnx' --dll 'E:/GNSS-Geo/.local/references/gnss-return08/rtklib_window_gate.dll' --output-root 'E:/GNSS-Geo/.local/runs/e6_rc1' --config local/runtime.json
```

配置助手只校验包和外部输入、填写本地路径，不运行导航。它从`SOURCE_MANIFEST.json`取得包内代码及科学配置摘要，生成`local/runtime.json`；不要直接运行带GENERATED/FILL字段的模板。实际Python默认采用运行助手的解释器，也可用--python显式指定。

默认窗口固定GPS周2158，96133.006至96152.006秒，步长1000000000纳秒，首末包含20个时刻；本次验收只使用这个窗口。保持GPS C1C、原观测顺序、原点/零钟差初始化和每历元重置，两种方法仅FDE开关不同，不使用参考轨迹初始化。

## 3. 预检与运行

```powershell
& 'E:/GNSS-Geo/.local/references/step39-raw-l1c/venv/Scripts/python.exe' -I -B -X utf8 tools/experiments/run_frozen_analysis.py --config local/runtime.json --run-id rc1-replay-next --dry-run
```

DRY_RUN_READY表示外层代码/外部输入/依赖检查完成，不解析全部OBS，也不运行导航。下面去掉--dry-run后会实际进行20×2组求解，每次必须换新的run-id：

```powershell
& 'E:/GNSS-Geo/.local/references/step39-raw-l1c/venv/Scripts/python.exe' -I -B -X utf8 tools/experiments/run_frozen_analysis.py --config local/runtime.json --run-id rc1-replay-next
```

输入不足或缺失时刻保留记录，原求解器拒绝、MODEL FALSE及REFERENCE UNKNOWN不触发自动重试。当前参考契约未提供，REFERENCE_VALID=UNKNOWN；运行成功不认证真实定位误差，未计算P95。

## 4. 输出与错误

输出位于配置output_root下的run-id，包含run_metadata、stdout/stderr、实际代码副本、replay的新状态、逐星模型、请求槽、五项资格、读取日志和first_party_modules。模型资格仅FINAL_RESIDUAL_DOMAIN_V1，不认证完整标定、全部迭代路径或物理同步。

INPUT_BLOCKED是配置/身份/输入准入问题；FAILED是执行、导出或规定比较异常；TIMED_OUT表示实际子进程超过60秒时限。查看run_metadata、stderr和failure_receipt的阶段及调用数。SOLVER_FAILURE属于科学结果分类，需结合accepted/converged和原消息判断主动拒绝或无解。INVALID_REFERENCE可包含UNKNOWN，不表示参考已经被证明错误。已有run-id会拒绝覆盖。

## 5. 源码身份与校验

`SOURCE_MANIFEST.json`列出包内全部交付文件的路径、大小、SHA256，排除清单自身以避免循环。snapshot_id由该文件列表的规范JSON计算；本地配置再固定清单的SHA256。压缩包本身的摘要在包外交付回执中，包内自洽检查不能替代该外部摘要。

无Git目录运行使用SOURCE_SNAPSHOT，当前head/branch为null，原科学commit只作为origin_scientific_commit。Git模式仍保留给原工作树。新建的local配置不属于原包清单，会单独记录身份；包内不应新增未登记Python代码。E0只附两项原字节身份锚点，不要求恢复其清单中的历史结果。

## 6. 测试与历史模式

包内自足测试仅需：

```powershell
& 'E:/GNSS-Geo/.local/references/step39-raw-l1c/venv/Scripts/python.exe' -I -B -X utf8 -m pytest tests/test_frozen_analysis_entry.py tests/test_engineering_baseline.py -q -p no:cacheprovider --basetemp 'E:/GNSS-Geo/.local/e6-tests/user-new'
```

basetemp必须在包外并采用新目录。与实际ZIP/运行有关的测试在未提供GNSS_E6_PACKAGE_ROOT、GNSS_E6_ZIP、GNSS_E6_FORBIDDEN_SOURCE、GNSS_E6_REAL_RUN时会明确跳过；它们读取已保存结果，不暗中调用导航。测试输入为临时合成身份文件，不含真实测量摘录。原工作树中依赖历史结果的E2—E5测试仍保留，本包没有复制那些历史输入或宣称其可脱离档案运行。

E1统一边界、E2保存结果适配器、E3/E4固定回放适配器和E5窗口代码均收录；历史模式需要另行提供其封存结果、脚本和配置，当前交付只验证无历史结果依赖的原OBS窗口路径。历史比较在新计算完成封存后单独进行，可使用window_urbannav.py的比较命令，不成为主运行前置条件。

不包含IMU融合、论文、历史实验档案、其他研究路线、第三方二进制或原始数据。当前工程基线候选版本不代表新算法、完整GNSS/IMU平台或论文交付。
