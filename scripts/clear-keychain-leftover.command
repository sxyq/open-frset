#!/bin/bash
# Frset 钥匙串残留一键清理
# 用途：若某天 Frset 又弹"想使用钥匙串"（例如之后重新签名过），双击本脚本清理一次即可。
#      清理后下次打开 Frset 会自动重建（不再弹窗）。
echo "== 清理 Frset 钥匙串条目 =="
security delete-generic-password -s "com.maoux.frset.anchor" 2>&1
echo
echo "完成。若显示 'password has been deleted' 即为成功。"
echo "之后再打开 Frset 将自动重建、不再弹窗。"
echo
read -n 1 -s -r -p "按任意键关闭..."
