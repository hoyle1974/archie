cd archie && find . | grep -v __pycache__ | while read a
do
echo "========= $a ========== START"
cat $a
echo "========= $a ========== DONE"
done | pbcopy
