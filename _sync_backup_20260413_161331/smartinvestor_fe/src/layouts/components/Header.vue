<template>
    <el-header class="header">
        <div class="header-left">
            <img src="../../assets/logo.png" alt="Logo" class="logo" />
            <span class="app-title">SmartInvestor</span>
            <div style="margin-left: 32px; min-width: 340px; max-width: 500px; width: 100%;">
                <el-menu mode="horizontal" class="header-menu" background-color="transparent" text-color="#333"
                    active-text-color="#409EFF" :border="false" style="flex: none; width: 100%;">
                    <el-menu-item index="dashboard">
                        <router-link to="/"
                            style="display: flex; align-items: center; text-decoration: none; color: inherit;">
                            <el-icon style="vertical-align: middle; margin-right: 6px;">
                                <HomeFilled />
                            </el-icon>
                            Dashboard
                        </router-link>
                    </el-menu-item>
                    
                    <el-menu-item index="valuation-pick">
                        <router-link to="/picking-valuation"
                            style="display: flex; align-items: center; text-decoration: none; color: inherit;">
                            <el-icon style="vertical-align: middle; margin-right: 6px;">
                                <DataAnalysis />
                            </el-icon>
                            估值选股
                        </router-link>
                    </el-menu-item>
                    <el-menu-item index="stock-pick">
                        <router-link to="/picking"
                            style="display: flex; align-items: center; text-decoration: none; color: inherit;">
                            <el-icon style="vertical-align: middle; margin-right: 6px;">
                                <Search />
                            </el-icon>
                            选股
                        </router-link>
                    </el-menu-item>
                </el-menu>
            </div>
            <el-autocomplete v-model="state" :fetch-suggestions="querySearchAsync" placeholder="请输入股票代码或名称"
                @select="handleSelect" clearable>
                <template #default="{ item }">
                    <div>
                        <div>
                            <span style="font-weight:bold; color:#409EFF; font-size:13px;">{{ item.name }} {{ item.ts_code }}</span>
                        </div>
                        <div>
                            <span style="color:#999; font-size:12px;">上市日期: {{ item.listdate }}</span>
                        </div>
                    </div>
                </template>
            </el-autocomplete>
        </div>
        <div class="header-right">

            <el-avatar :src="userPhoto" size="default" class="user-avatar"></el-avatar>
            <span class="user-name">{{ userName }}</span>
        </div>
    </el-header>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import axios from 'axios'
import { ElMenu, ElMenuItem, ElIcon, ElHeader, ElAvatar } from 'element-plus'
import avatarImg from '../../assets/avatar.png'
import { HomeFilled, Search, DataAnalysis } from '@element-plus/icons-vue'
// Element Plus
import { ElAutocomplete } from 'element-plus'
import { inject } from 'vue'
// store
import { useStockTradeStore } from '../../stores/stockTradeStore'

const baseURL = inject('baseURL')
const stockTradeStore = useStockTradeStore()
const state = ref('')
const userName = ref('John Doe')
const userPhoto = ref(avatarImg)

const querySearchAsync = (queryString: string, cb: (arg: any) => void) => {
    if (!queryString) {
        cb([])
        return
    }
    axios.get(`${baseURL}/corporations/${encodeURIComponent(queryString)}/`)
        .then(res => {
            cb(res.data.data)
        })
        .catch(() => cb([]))
}


const handleSelect = (item: Record<string, any>) => {
    state.value = item.name + ' ' + item.ts_code
    stockTradeStore.setTsCode(item.ts_code)
    stockTradeStore.setName(item.name)
    console.log(item)
}

</script>

<style scoped>
.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0 24px;
    background: #fff;
    height: 64px;
    box-shadow: 0 2px 10px #f0f1f2;
}

.header-left {
    display: flex;
    align-items: center;
}

.logo {
    height: 40px;
    margin-right: 12px;
}

.app-title {
    font-size: 20px;
    font-weight: bold;
    color: #333;
}

.header-menu {
    border-bottom: none !important;
    box-shadow: none !important;
    /* 如果有阴影也一并去除 */
}

.header-right {
    display: flex;
    align-items: center;
}

.user-avatar {
    margin-right: 8px;
}

.user-name {
    font-size: 16px;
    color: #333;
}
</style>