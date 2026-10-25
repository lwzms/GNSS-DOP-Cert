# GNSS118 内部源码交付候选

**仅支持已冻结的UrbanNav固定20历元合同。** GPST 2021-05-17 02:42:13.006—02:42:32.006，GPS周2158、TOW96133.006—96152.006；方法仅SPP及SPP_FDE，GPS C1C。其他RINEX、窗口、机器和Python构建尚未验收。E18只进行了非导航工程核查，真实导航证据沿用E17；本目录没有新的40请求结果。

版本为 `GNSS118_INTERNAL_HANDOFF_CANDIDATE_V1`，核心仍为E17的 `GNSS118_INTERNAL_TOOLBOX_CANDIDATE_V1` 派生包。此目录供项目负责人授权的内部开发者使用，未赋予公开再分发许可；尚未发生真实独立使用者交付。未知授权的OBS、NAV、DLL、解释器、NumPy及数值后端均不在本目录。

## 1. 准备资源

使用者自行取得合法OBS、NAV及指定哈希的Windows AMD64 RTKLIB包装DLL，并准备64位CPython3.13.5、NumPy2.1.3和所需Windows/UCRT运行时。本机历史验收使用Anaconda MKL构建；同NumPy版本号无法保证不同后端逐位一致。E13的CPython3.13.3/OpenBLAS证据不代表本版本部署通过。当前没有可认证的独立安装器或离线依赖集合，不应盲目执行pip安装并宣称环境等价。requirements只是已测试版本记录。

外部文件身份见 `external_inputs_contract.json`；系统及ABI见 `environment_contract.json`；许可证据与未解决事项见 `docs/license_ledger.json`。其中历史本机路径仅作来源举例，公共入口不把它们作为默认输入。

## 2. 目录和配置

将本候选完整复制到一个本地目录；候选内不能添加pycache、日志或临时文件，否则完整目录清单核验会拒绝。将 `config.template.json` 复制到候选目录之外的工作目录，例如 `C:/GNSS118-work/config.json`。替换Python及三项外部文件路径，填写解释器真实SHA256；保留科学字段、输入哈希与版本。输出使用 `runs`，它会解析为配置目录下的子目录。给每次运行使用新的run_id。

所有配置路径只接受本地盘符绝对路径或相对于配置文件目录的路径；不展开环境变量、波浪号或通配符。明确拒绝UNC、设备路径、`C:relative`、无盘符根路径、ADS、Windows保留名及末尾空格/句点。UNC目前未验收，不会尝试网络访问。`../`仅在输入路径中按配置根正常解析；输出规范化后必须仍在配置目录的专用子目录内。路径不存在时错误详情包含实际尝试位置。

## 3. 命令

下列命令中的变量由使用者填写，无自动下载、安装或环境变更：

```powershell
$py = 'C:/your-authorized-python/python.exe'
$tool = 'C:/your-copy/handoff_candidate/toolbox.py'
$config = 'C:/GNSS118-work/config.json'
& $py -I -B -X utf8 $tool --version
& $py -I -B -X utf8 $tool preflight --config $config
# 以下run会执行40次真实导航；E18未执行，需使用者另行授权运行。
& $py -I -B -X utf8 $tool run --config $config
& $py -I -B -X utf8 $tool verify --run-dir 'C:/GNSS118-work/runs/your_unique_run'
```

preflight核对包清单、配置、文件摘要、解释器及DLL导出，仅加载DLL，不调用导航函数；它会在输出目录创建并删除写入探针。verify只读核验封存，不运行导航。保存结果的来源绑定仍需要对应配置、代码和输入文件保持可访问及相同字节；把历史run单独搬走并不会生成新的完整来源合同。版本清单必须与独立提供的交付摘要核对；SHA256是完整性检查，不是数字签名或作者身份认证。

普通模式 `INTERNAL_STANDARD_RUN_V1` 必须令 `historical_comparison=null`，无需E11/E5/E4历史结果，历史比较返回NOT_REQUESTED。开发审核模式 `EXACT_HISTORICAL_REGRESSION_V1` 需要显式历史合同及其SHA256，缺少材料将拒绝；compare可只读执行零容差比较，有限DOP证书不会覆盖严格失败。

## 4. 状态及错误处理

accepted和converged保持求解器原含义。OBS_VALID、NAV_VALID、MODEL_VALID、SOLVER_VALID、REFERENCE_VALID分别保存；accepted为TRUE且MODEL_VALID为FALSE仍是INVALID_MODEL_OUTPUT。REFERENCE_UNKNOWN表示缺少合格外部参考，不能解释为精度合格；UNKNOWN与NA不可填零。

返回分层包括science_execution、runtime_recording、qualification、historical_regression、numerical_certificate、delivery。预检失败返回退出码2和当前导航0；运行开始后失败保留实际已返回调用数，来源不足则UNKNOWN；只读verify当前导航0与被核验历史run的40次调用分别展示。完整运行失败证据不得删除后复用同run_id。

主要错误包括NUMPY_MISSING、NUMPY_IMPORT_FAILED、DLL_LOAD_FAILED、OBS/NAV/DLL_MISSING、各HASH_MISMATCH、UNSUPPORTED_METHOD、INVALID_TIME_RANGE、OUTPUT_PATH_PROTECTED、RUN_ID_EXISTS、PACKAGE_FILE_HASH_MISMATCH、PACKAGE_INVENTORY_MISMATCH、SEALED_OUTPUT_HASH_MISMATCH及SEALED_INVENTORY_CHANGED。缺少NumPy时版本查询仍可执行，记录核验和预检给出结构化错误；解释器本身缺失时操作系统无法启动CLI，调用方须处理启动失败。

## 5. 测试、范围和回滚

`tests/test_delivery.py` 是不调用导航的路径和合同检查，结果写入用户指定的候选外目录。保留的 `tests/test_contracts.py` 属于E17开发检查，依赖显式历史夹具，不能冒充普通使用依赖，也不在E18重新执行其DOP算术检查。vendor中的旧README及试验脚本仅用于追溯，生产入口以本文件为准。

不包含新Huber、载波窗口、Doppler速度、FUSED_CODE、IMU融合或VQ-MAST生产模块。研究算法状态仍为NO_MECHANISM_ADMITTED，公开发行NOT_READY。

回滚时停止使用此E18候选，直接使用未修改的E17候选及其原配置，不覆盖历史文件。E17路径在项目历史报告中可查；交付给他人时若需回滚材料，由项目负责人另行提供其获准副本。只有内部授权、独立机器安装以及完整许可证据分别确认后，才可另议部署和公开发行；本目录不自动批准这些操作。
