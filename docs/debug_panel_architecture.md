# Debug Panel 架构说明

## 目标
将调试面板按「UI 组件 / Tab 内容 / 运行逻辑」拆分，降低单文件复杂度，避免改动互相影响。

## 当前模块划分

### 入口与调度
- widgets/debug_panel.py
  - 负责弹窗生命周期（open/close）
  - 负责 Tab 注册、懒加载、切换事件
  - 负责调用各 Tab 构建函数
  - 仅保留薄代理方法，具体业务下沉到 runtime

### 通用 UI 组件
- widgets/debug_ui_components.py
  - TechButton
  - SquareTechButton
  - DangerButton
  - ServoStatusCard

### Tab 内容组件
- widgets/debug_actions_tab.py
  - 快捷动作 Tab 的内容构建与按钮布局
- widgets/debug_status_tab.py
  - 连接状态 Tab 的内容容器与状态网格创建
- widgets/debug_single_servo_tab.py
  - 关节调试 Tab 的完整 UI 与交互逻辑（读回自检等）
- widgets/debug_ai_model_tab.py
  - AI 模型 Tab 内容构建
- widgets/debug_other_settings_tab.py
  - 高级设置 Tab 内容构建

### 运行逻辑
- app/debug_panel_runtime.py
  - Demo 启动与执行
  - 归零写 ID 脚本启动
  - 紧急释放扭矩
  - 连接状态数据刷新与卡片渲染
  - 动作分发调用
  - 通用提示弹窗

## 调用关系（简图）
1) 用户打开调试面板
2) debug_panel.py 创建 Popup + Tab 容器
3) 点击 Tab 时触发懒加载，调用对应 build_*_tab_content
4) 运行类行为（Demo、刷新状态、动作执行等）通过 debug_panel_runtime.py 完成
5) runtime 结果通过 UI 回调反映到弹窗

## 扩展约定

### 新增一个 Tab
1) 在 widgets 下新建 debug_xxx_tab.py，提供 build_xxx_tab_content(tab_item, ...)
2) 在 debug_panel.py 中注册懒加载：_register_lazy_tab(...)
3) 如需业务逻辑，放到 app/debug_panel_runtime.py 或新的 runtime 模块

### 新增一个运行动作
1) 在 app/debug_panel_runtime.py 增加函数
2) 在 debug_panel.py 中保持薄代理调用
3) Tab 组件只绑定事件，不直接写复杂业务

## 维护建议
- UI 文件只做布局与交互绑定，不做复杂设备逻辑
- 设备通信与状态计算集中放 runtime
- 复杂逻辑优先可测试的纯函数化，减少对 Kivy 控件实例的耦合
