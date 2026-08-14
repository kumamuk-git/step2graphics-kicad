# STEP Projection Importer for KiCad

STEPモデルを6方向から正投影し、KiCad 10 PCB Editorへ線グラフィックとして読み込むAction Pluginです。

![KiCad](https://img.shields.io/badge/KiCad-10.0-314CB0)
![Platform](https://img.shields.io/badge/platform-Windows-0078D4)
![Version](https://img.shields.io/badge/version-0.3.2-green)

## 機能

- `.step` / `.stp` のファイル選択とドラッグ＆ドロップ
- `±X` / `±Y` / `±Z` の6方向投影
- 読み込み前の平面プレビュー
- 表示線・隠線の切り替え
- 同一直線上に分割された線分の統合
- 生成アイテムのグループ化と選択
- `Dwgs.User`、`Edge.Cuts`、`F.Fab`などへの直接配置
- Docker・Webサーバー不要

STEP解析にはOpenCASCADEを使用します。初回実行時にプラグイン専用Python環境へ依存パッケージをインストールします。

## インストール

### PCMリポジトリからインストール

KiCadの「プラグイン＆コンテンツ マネージャー」から「リポジトリを管理」を開き、次のURLを追加します。

```text
https://raw.githubusercontent.com/kumamuk-git/step2graphics-kicad/refs/heads/main/repository.json
```

追加後、リポジトリを`STEP Projection Importer Repository`へ切り替えて更新すると、`STEP Projection Importer`を一覧からインストールできます。

### ZIPからインストール

1. [最新のPCMパッケージ](kicad_plugin/pcm/dist/step2graphics-kicad10-action-plugin-0.3.2.zip)を取得する。
2. KiCadの「プラグイン＆コンテンツ マネージャー」を開く。
3. 「ファイルからインストール…」でZIPを選ぶ。
4. 保留中の変更を適用し、PCB Editorを再起動する。
5. `ツール > 外部プラグイン > STEP投影をグラフィックとして読み込む`を実行する。

初回の投影時のみ、`cadquery-ocp-novtk`の取得にインターネット接続が必要です。

## 使い方

1. 読み込みダイアログへSTEPファイルをドラッグ＆ドロップする。
2. 投影方向を選び、平面プレビューを確認する。
3. レイヤー、線幅、配置中心、線分統合条件などを指定する。
4. 「読み込む」を押す。

生成線分は既定で`STEP投影: ファイル名`という1グループになり、そのグループが選択されます。同一直線上の線分は、既定で端点許容差`0.001 mm`、角度許容差`0.05°`の範囲で統合されます。角をまたいだ統合は行いません。
