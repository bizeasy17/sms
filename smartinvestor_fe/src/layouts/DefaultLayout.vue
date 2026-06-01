<template>
  <div class="common-layout" style="overflow-x: hidden; width: 100vw; max-width: 100vw;">
    <el-container class="full-screen-container">
      <el-header class="custom-header">
        <Header />
      </el-header>
      <el-container style="overflow-x: hidden; width: 100vw; max-width: 100vw;">
        <el-aside class="custom-aside" style="height: 100%; width: auto; flex: 0 0 auto;"></el-aside>
        <el-main>
            <slot></slot>
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>
<script setup>
import Header from './components/Header.vue'
// element plus
import { ElContainer, ElHeader, ElAside, ElMain } from 'element-plus'
// import Sidebar from '../components/Sidebar.vue'
</script>
<style scoped>
.full-screen-container,
.common-layout {
  height: 100vh;
  width: 100vw;
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

.custom-header {
  color: #cc1717;
  margin: 0;
  padding: 0;
  /* border-bottom: 1px solid #dcdfe6; */
}

.custom-aside {
  color: #d44f4f;
  margin: 0;
  padding: 0;
  /* border-right: 1px solid #dcdfe6; */
}

.custom-main {
  color: #f55656;
  margin: 0;
  padding: 0;
}

:global(html),
:global(body),
:global(#app) {
  height: 100%;
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}
</style>