<script setup lang="ts">
// Login View
</script>

<template>
  <div class="login">
    <h1>Login to SysRoar</h1>
    <form>
      <input type="text" placeholder="Username" />
      <input type="password" placeholder="Password" />
      <button type="submit">Login</button>
    </form>
  </div>
</template>

<style scoped>
.login { padding: 2rem; display: flex; flex-direction: column; align-items: center; }
form { display: flex; flex-direction: column; gap: 1rem; width: 300px; }
input { padding: 0.5rem; }
button { padding: 0.5rem; cursor: pointer; }
</style>
