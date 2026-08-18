import { createRouter, createWebHistory } from 'vue-router';
import type { RouteRecordRaw } from 'vue-router';

const routes: Array<RouteRecordRaw> = [
    {
        path: '/',
        name: 'Dashboard',
        component: () => import('../views/DashboardView.vue'),
    },
    {
        path: '/opt/stock-research-dashboard',
        name: 'OptStockResearchDashboard',
        component: () => import('../views/OptStockResearchDashboardView.vue'),
    },
    {
        path: '/market',
        name: 'Market',
        component: () => import('../views/MarketView.vue'),
    },
    {
        path: '/picking',
        name: 'Picking',
        component: () => import('../views/SmartStockPickingView.vue'),
    },
    {
        path: '/picking-valuation',
        name: 'ValuationPicking',
        component: () => import('../views/ValuationStockPickingView.vue'),
    },
    {
        path: '/sw-industry',
        name: 'SwIndustry',
        component: () => import('../views/SwIndustryView.vue'),
    },
    {
        path: '/supply-chain',
        name: 'SupplyChainGraph',
        component: () => import('../views/SupplyChainGraphView.vue'),
    },
    {
        path: '/backtest-execute',
        name: 'BacktestExecute',
        component: () => import('../views/BacktestExecuteView.vue'),
    },
    {
        path: '/backtest-query',
        name: 'BacktestQuery',
        component: () => import('../views/BacktestQueryView.vue'),
    },
    {
        path: '/schedule-jobs',
        name: 'ScheduleJobs',
        component: () => import('../views/ScheduleJobsView.vue'),
    },
    // Add more routes here as needed
];

const router = createRouter({
    history: createWebHistory(),
    routes,
});

export default router;