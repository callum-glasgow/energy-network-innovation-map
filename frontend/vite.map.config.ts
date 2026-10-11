import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig({root:'map',base:'./',plugins:[react(),tailwindcss()],build:{outDir:'../map-dist',emptyOutDir:true}});
