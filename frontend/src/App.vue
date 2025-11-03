<!-- src/App.vue -->
<template>
  <!-- 根容器 -->
  <div id="app">
    <!-- 路由出口：所有页面都会在这里渲染 -->
    <router-view />
  </div>
</template>

<script setup>
// 根组件通常不需要复杂逻辑，仅作为容器
</script>

<style scoped>
/* 全局基础样式（可选） */
#app {
  width: 100%;
  height: 100vh;
  overflow: hidden;
  margin: 0px;
  padding: 0px;
}
</style>