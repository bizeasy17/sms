import { createRouter, createWebHistory } from 'vue-router';
import type { RouteRecordRaw } from 'vue-router';

const routes: Array<RouteRecordRaw> = [
    {
        path: '/',
        name: 'Dashboard',
        component: () => import('../views/DashboardView.vue'),
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
    // Add more routes here as needed
];

const router = createRouter({
    history: createWebHistory(),
    routes,
});

export default router;