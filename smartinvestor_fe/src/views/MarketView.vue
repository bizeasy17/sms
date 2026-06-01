<template>
	<DefaultLayout>
		<el-row :gutter="24">
			<el-col :span="24">
				<el-card>
					<template #header>
						<span>市场总览</span>
					</template>
					<el-empty description="市场页功能建设中" />
				</el-card>
			</el-col>
		</el-row>
	</DefaultLayout>
</template>

<script setup lang="ts">
import DefaultLayout from "../layouts/DefaultLayout.vue";
import { ElRow, ElCol, ElCard, ElEmpty } from "element-plus";
</script>

<style>
.el-row {
	margin-bottom: 20px;
}

.el-row:last-child {
	margin-bottom: 0;
}
</style>
