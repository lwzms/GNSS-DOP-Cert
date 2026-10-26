# 共同作者复现说明

**本版本仅覆盖固定20历元的GPS C1C SPP/FDE案例。** 仓库保持Private，需要项目负责人向共同作者的GitHub账号提供读取权限；本次没有代为邀请任何账号。本文将保存结果复核与重新运行定位分开，完成前者不能登记为后者通过。

最新的可执行数据下载、环境清单、自动生成本机配置及公共预检步骤，集中在[Windows准备指南](SETUP_WINDOWS.md)。项目负责人已授权随私下论文材料包提供指定DLL；该DLL及论文正文不会上传GitHub。

## 1. 获取确定版本

在获得读取权限后克隆`https://github.com/LACANIA/GNSS-ToolBox-118`，记录`git rev-parse HEAD`输出，并以项目负责人提供的提交SHA核对。不要从旧研究仓库复制分支，也不要把论文正文放入本代码仓库。证据包清单的SHA256用于内容完整性检查，不是数字签名；需要通过可信的GitHub提交身份或另行交付摘要建立信任起点。

## 2. 先复核论文证据：不需要原始数据和DLL

从仓库根目录执行，使用已合法安装的Python。该路径仅使用标准库，不导入NumPy、不加载GNSS DLL、不依赖Anaconda或原开发目录。当前本地测试版本与结果记录在本次提交的技术验证说明中；其他解释器版本未被自动认证。

```powershell
python --version
git rev-parse HEAD
python -I -B reproduce/verify_paper_evidence.py
python -I -B reproduce/test_paper_evidence.py
```

第一条验证命令只向终端输出JSON；若需保存回执，将stdout重定向到仓库以外的新文件。成功退出码为0，失败为2。不要在`toolbox/`或`evidence/urban_spp_fde_v1/`中生成日志、缓存、临时文件或编辑数据，完整目录清单会拒绝额外成员。

预期：80项证书重算、480项NPY身份与位模式核对、160项DOP配对、131项差异、最大绝对差`9.237055564881302e-12`。两个环境各40项历史调用，本次调用为0；每环境SPP/FDE accepted为7/11，MODEL_TRUE为18/17，REFERENCE_UNKNOWN为40。每环境GDOP区域36项在门限内、4项高于30。索引548的FDE结果继续同时具有accepted TRUE、MODEL FALSE和INVALID_MODEL_OUTPUT。

程序直接从保存矩阵重算有限输入证书，再核对保存证书。这里沿用已经交付的准确有理数实现，没有声称第二套独立证明程序。H的920个元素相同，生产Gram差异256/640，生产Q差异594/640；E15的587/640是固定同一Gram输入下的另一项离线对照，不能混写成生产Q差异数。

完整12965字段的历史零差比较回执已经列出，但本包未包含所有原始卫星明细和完整run依赖，因此该验证程序不会声称重新执行了12965字段比较。E13及E16跨环境严格失败状态保持；有限输入证书不覆盖EXACT_REPLAY_SCIENCE_V1失败。

## 3. 如需在你的电脑重新运行SPP/FDE

先取得[数据来源说明](DATA_SOURCES.md)中的OBS、NAV和指定DLL，以及合法Windows AMD64、64位CPython3.13.5、NumPy2.1.3 MKL构建和对应系统运行时。当前工具的普通生产配置冻结在该环境合同。相同NumPy版本号不保证相同BLAS；E13的CPython3.13.3/OpenBLAS历史证据不意味着本候选已经支持任意切换环境。

`evidence/urban_spp_fde_v1/environments.json`提供实际历史解释器、后端和二进制摘要。它不是安装包，也没有给出未经测试的版本兼容范围。当前仓库尚无完整离线安装器；若无法合法取得匹配DLL或运行环境，登记依赖阻塞，仍可完成第2节的证据复核。不得用同名DLL、不同NAV或另一个接收机文件替换。

在仓库外新建工作目录，将`toolbox/config.template.json`复制为该目录下的`config.json`。填写Python和OBS/NAV/DLL路径及Python真实SHA256，保留原科学字段、三个固定输入哈希、模式`INTERNAL_STANDARD_RUN_V1`及`historical_comparison=null`；为`run_id`指定未使用过的名称，`output_root`使用配置目录内的`runs`子目录。无GT、历史位置或旧accepted标签进入初始化。

```powershell
Get-FileHash -Algorithm SHA256 'C:/your-authorized-python/python.exe'
Get-FileHash -Algorithm SHA256 'C:/your-data/UrbanNav-HK-Medium-Urban-1.ublox.f9p.splitter.obs'
Get-FileHash -Algorithm SHA256 'C:/your-data/BRDM00DLR_S_20211370000_01D_MN.rnx'
Get-FileHash -Algorithm SHA256 'C:/your-dll/rtklib_window_gate.dll'
$py = 'C:/your-authorized-python/python.exe'
$tool = 'C:/your-repository/GNSS-ToolBox-118/toolbox/toolbox.py'
$config = 'C:/GNSS118-author-work/config.json'
& $py -I -B -X utf8 $tool --version
& $py -I -B -X utf8 $tool preflight --config $config
# 仅在来源、授权及预检通过后，由使用者决定执行一次40请求真实运行。
& $py -I -B -X utf8 $tool run --config $config
& $py -I -B -X utf8 $tool verify --run-dir 'C:/GNSS118-author-work/runs/your_unique_run'
```

以上路径是需要替换的示例。绝对路径按本地盘符解析，相对路径以配置文件目录为根；不支持UNC、设备路径、环境变量展开或保留设备名。输出不得越出配置允许目录，已有run_id拒绝覆盖。preflight会加载指定DLL检查ABI，并建立及删除写入探针，但不会求解导航；verify只读，仍要求完整run的外部来源可访问且字节相同。不要把这里的完整run verify与第2节便携证据验证器混同。

普通运行不需要E11/E5/E4旧结果，历史比较应返回NOT_REQUESTED。若需要完整严格比较，由负责人另行提供获准的完整比较合同及源文件；不能把本包的历史摘要直接注入为新运行的通过证明。新运行保留自己的全部输出、配置、解释器身份和退出码；发生差异时保留失败，禁止放宽容差、改变窗口或反复调参。

## 4. 如何解读与返回复现结果

数值converged、求解器accepted、MODEL_VALID、SOLVER_VALID和REFERENCE_VALID分别报告。UNKNOWN与NA保留原含义，不能填0。accepted为TRUE且MODEL_VALID为FALSE时仍拒绝科学模型输出；REFERENCE_UNKNOWN不允许产生精度结论。

请将实际提交SHA、操作系统及Python版本、使用的命令、stdout/stderr、退出码和验证结果返回项目负责人；不要公开上传个人机器路径或未知许可的外部输入。完成第2节时记为“保存证据复核”；只有你的电脑实际完成第3节并经过来源与回归审核，才能登记独立导航复现。当前尚未发生真实共同作者部署验证，公开发行资格也未成立。
