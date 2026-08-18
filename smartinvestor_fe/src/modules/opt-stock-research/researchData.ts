export type ResearchCompany = {
    name: string;
    code: string;
    industry: string;
    tags: string[];
    isHolding?: boolean;
    status?: string;
    statusTone?: 'good' | 'warn';
    price: string;
    change: string;
    verdict: string;
    thesis: string;
    position: string;
};

export const researchCompanies: ResearchCompany[] = [
    { name: '大华股份', code: '002236.SZ', industry: '安防设备', tags: ['自', '注'], status: '传统低估', statusTone: 'good', price: '16.39', change: '+0.08  +0.49%', verdict: '中性持有', thesis: '低估与预期定价并存，业绩是下一次重估的唯一催化。', position: '60-75% 仓位' },
    { name: '燕京啤酒', code: '000729.SZ', industry: '食品饮料', tags: ['自', '注'], status: '传统低估', statusTone: 'good', price: '12.86', change: '+0.04  +0.31%', verdict: '谨慎持有', thesis: '品牌势能和成本改善仍在兑现，估值修复需要盈利继续验证。', position: '45-60% 仓位' },
    { name: '百普赛斯', code: '301080.SZ', industry: '医疗服务', tags: ['自', '注'], status: '财报待更新', price: '53.20', change: '-0.31  -0.58%', verdict: '等待确认', thesis: '增长假设仍需以最新财报和订单数据重新校准。', position: '25-40% 仓位' },
    { name: '宇通客车', code: '600066.SH', industry: '汽车', tags: ['自', '持', '注'], status: '盈利上修', statusTone: 'good', price: '29.62', change: '+0.36  +1.23%', verdict: '积极持有', thesis: '出口与产品结构改善提供业绩弹性，关注估值消化速度。', position: '65-80% 仓位' },
    { name: '宁德时代', code: '300750.SZ', industry: '电力设备', tags: ['自', '注'], status: '传统低估', statusTone: 'good', price: '221.50', change: '+1.20  +0.54%', verdict: '中性持有', thesis: '行业供需格局改善仍待确认，安全边际已开始形成。', position: '50-65% 仓位' },
    { name: '美的集团', code: '000333.SZ', industry: '家用电器', tags: ['自', '持', '注'], status: '稳定跟踪', price: '74.18', change: '+0.21  +0.28%', verdict: '稳定持有', thesis: '现金流稳健，等待海外业务和利润率的边际变化。', position: '55-70% 仓位' },
    { name: '海康威视', code: '002415.SZ', industry: '安防设备', tags: ['自', '注'], status: '模型中位', statusTone: 'warn', price: '31.41', change: '-0.09  -0.29%', verdict: '中性观察', thesis: '估值处于合理区间，后续需要订单恢复提供方向。', position: '35-50% 仓位' },
];