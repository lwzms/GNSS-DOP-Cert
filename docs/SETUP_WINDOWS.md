# 共同作者的Windows配置与数据准备

此说明只适用于原固定20历元案例。本文的项目DLL由负责人另行私下交付，不在GitHub内；论文材料也通过私下材料包交付。当前仓库提供代码、派生证据、来源说明和下列准备工具。

## 1. 先核查保存证据

取得Private仓库读取权限，下载或克隆整个仓库后，使用本机Python执行：

```powershell
python -I -B reproduce/verify_paper_evidence.py
python -I -B reproduce/test_paper_evidence.py
python -I -B reproduce/test_data_preparation.py
```

这一步无需NumPy、原OBS/NAV或DLL，预期返回80项证书、160项DOP配对及131项差异。记录退出码和仓库提交。该路径已经完成本机独立目录测试；尚未由共同作者实际执行。

## 2. 取得两份外部数据

2026-10-26实际下载并核对过以下文件，解压后的SHA256与冻结输入完全一致。原始文件不会加入代码仓库或论文交接包。

- OBS：[UrbanNav Medium-Urban-1 GNSS归档](https://www.dropbox.com/sh/2haoy68xekg95zl/AAAkcN4FwhFxkPY1lXsxbJrxa?dl=1)，22526745字节；只取`UrbanNav-HK-Medium-Urban-1.ublox.f9p.splitter.obs`。
- NAV：[BKG的2021年第137天BRDM压缩文件](https://igs.bkg.bund.de/root_ftp/IGS/BRDC/2021/137/BRDM00DLR_S_20211370000_01D_MN.rnx.gz)，1244184字节；解压为`BRDM00DLR_S_20211370000_01D_MN.rnx`。旧MGEX/BRDC_v3路径本次返回404，不使用。

使用者按提供方条件合法取得资料后，可以显式执行以下下载工具。目标目录必须尚未存在且位于仓库之外；程序只解压指定成员，先核对归档与输入文件哈希，再写出两份文件及获取回执，不解析GNSS观测。

```powershell
python -I -B reproduce/download_case_data.py --destination C:/GNSS118-author/data
```

如果网络限制使自动下载失败，可通过上面的浏览器地址下载并解压，再按照[数据来源说明](DATA_SOURCES.md)核对两份原文件。返回HASH_MISMATCH时保留错误回执，联系负责人确认来源，不能删去校验或更换文件。归档中的其他观测与传感器资料不进入本案例。

## 3. 建立明确版本的科学运行环境

生产入口需要Windows AMD64、CPython3.13.5、NumPy2.1.3及MKL构建。当前Python版本相同或Windows版本相同，并不证明数值后端相同。

`reproduce/environment/win64-mkl-explicit.txt`列出原环境中Python和NumPy依赖闭包的27个已安装包，固定URL、版本、构建号及MD5；相应SHA256和依赖关系在`package_sources.json`中。这里包括包管理所需依赖，不能将27个包全称为导航代码直接导入依赖。27个下载地址已完成HTTP HEAD检查，均返回200；尚未在全新机器完成安装验收。

使用已合法安装的Conda，并确认你所属机构适用的获取渠道条款。清单引用Anaconda官方渠道，不分发这些二进制包，也不授予渠道或软件许可。若渠道不可用，先与负责人确认，不能静默替换为其他BLAS构建。Conda的明确包清单机制可参照[官方环境管理说明](https://docs.conda.io/projects/conda/en/latest/user-guide/tasks/manage-environments.html)；以下参数也已与本机Conda帮助核对。

```powershell
$repo = 'C:/your-copy/GNSS-ToolBox-118'
$envdir = 'C:/GNSS118-author/env-mkl'
conda create --prefix $envdir --no-default-packages --file "$repo/reproduce/environment/win64-mkl-explicit.txt"
conda run --prefix $envdir --no-capture-output python -I -B -c "import sys,numpy; print(sys.version); print(numpy.__version__); numpy.show_config()"
```

将安装及环境输出保存在仓库以外。不要直接用系统Python替代`conda run`指定的环境，也不要执行未声明的库升级。本清单已依据原已安装元数据建立，当前仍需在接收者电脑上实际确认；本机原环境的通过不能代替接收者安装通过。

## 4. 配置指定DLL及固定科学输入

私下材料包的`private_runtime/rtklib_window_gate.dll`是负责人已明确授权向该合作者提供的构建，SHA256为`fabf66b6dcfccb3893c21c4bca7617ee00a8caaf5684a98cd058cf953b60f5a9`。这份内部交接授权没有扩大为公开再分发许可。只复制该文件到获准的本地位置，Windows系统库由本机合法运行时提供，不从其他电脑复制系统DLL。

下面的辅助工具会核对Windows位数、Python/NumPy/MKL身份以及三个文件的哈希，生成具有本机路径的新配置，不调用GNSS DLL或导航求解。工作目录必须不存在；科学参数与原模板保持相同。

```powershell
conda run --prefix $envdir --no-capture-output python -I -B "$repo/reproduce/prepare_run_config.py" --obs C:/GNSS118-author/data/UrbanNav-HK-Medium-Urban-1.ublox.f9p.splitter.obs --nav C:/GNSS118-author/data/BRDM00DLR_S_20211370000_01D_MN.rnx --dll C:/your-private-package/private_runtime/rtklib_window_gate.dll --work-dir C:/GNSS118-author/work01 --run-id author_case_01
conda run --prefix $envdir --no-capture-output python -I -B "$repo/toolbox/toolbox.py" preflight --config C:/GNSS118-author/work01/config.json
```

本机已经用新配置生成器和原合法环境执行公共preflight，返回PREFLIGHT_READY，导航调用为0。预检会加载指定DLL检查ABI并创建及删除写入探针。若接收者缺少系统运行时或遇到DLL加载失败，应保留错误，不从网络搜索任意同名DLL替代。

## 5. 接收者实际执行与保存

只有预检通过且使用者决定开展复现时，才执行下列真实运行；该命令将产生40项导航请求，本次交接整理没有执行它。

```powershell
conda run --prefix $envdir --no-capture-output python -I -B "$repo/toolbox/toolbox.py" run --config C:/GNSS118-author/work01/config.json
conda run --prefix $envdir --no-capture-output python -I -B "$repo/toolbox/toolbox.py" verify --run-dir C:/GNSS118-author/work01/runs/author_case_01
```

普通模式的历史回归必须为NOT_REQUESTED，不能把没有请求的比较记为通过。保留完整运行目录、配置、环境输出、命令和退出码，再由作者核查新结果与保存证据的关系。原数值参考为SPP/FDE accepted 7/11、MODEL_TRUE 18/17、REFERENCE_UNKNOWN共40；这只是冻结案例的对照，不是程序可以补造的期望输出。若出现差异，保留原结果，禁止通过调参、改门限或放宽比较容差产生通过。

论文可以继续基于已封存数据写作；共同作者的实际运行应具有新的身份与日期，并作为新增复现证据明确区分。不能把本次数据下载、环境清单或预检登记为新机器导航已完成。
