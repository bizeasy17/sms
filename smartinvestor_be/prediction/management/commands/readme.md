<!-- prediction command execution steps -->

<!-- 从trade，funda和cost获取原始数据，并计算技术指标，分位数等基本特征数据，存入STockFeature表 -->
extractfeat

<!-- 进一步计算特征数据，存入StockCombinedFeature -->
combinedata

<!-- 从StockCombinedFeature中获取特征数据，并预测，结果存入StockPredictionResult -->
predict