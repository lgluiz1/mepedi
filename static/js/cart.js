/**
 * IA-Pedidos - Gerenciador do Carrinho e Modal de Opções (Mobile-First)
 */

class IAPedidosCart {
  constructor(storeSlug) {
    this.storeSlug = storeSlug;
    this.storageKey = `ia_cart_${storeSlug}`;
    this.items = this.loadFromStorage();
    this.catalog = {};
    this.activeProduct = null;
    this.modalQuantity = 1;
    this.init();
  }

  init() {
    const catalogEl = document.getElementById('store-catalog-data');
    if (catalogEl) {
      try {
        this.catalog = JSON.parse(catalogEl.textContent);
      } catch (e) {
        console.error("Erro ao carregar catálogo:", e);
      }
    }
    this.bindEvents();
    this.renderCartUI();
  }

  loadFromStorage() {
    try {
      const data = localStorage.getItem(this.storageKey);
      return data ? JSON.parse(data) : [];
    } catch (e) {
      console.error("Erro ao carregar carrinho:", e);
      return [];
    }
  }

  saveToStorage() {
    try {
      localStorage.setItem(this.storageKey, JSON.stringify(this.items));
    } catch (e) {
      console.error("Erro ao salvar carrinho:", e);
    }
  }

  addItem(item) {
    this.items.push(item);
    this.saveToStorage();
    this.renderCartUI();
  }

  updateQuantity(index, delta) {
    if (this.items[index]) {
      this.items[index].quantity += delta;
      if (this.items[index].quantity <= 0) {
        this.items.splice(index, 1);
      }
      this.saveToStorage();
      this.renderCartUI();
    }
  }

  removeItem(index) {
    if (this.items[index]) {
      this.items.splice(index, 1);
      this.saveToStorage();
      this.renderCartUI();
    }
  }

  clear() {
    this.items = [];
    this.saveToStorage();
    this.renderCartUI();
  }

  getItemCount() {
    return this.items.reduce((acc, item) => acc + item.quantity, 0);
  }

  getSubtotal() {
    return this.items.reduce((acc, item) => {
      const optionsTotal = item.options.reduce((sum, opt) => sum + (Number(opt.price) || 0), 0);
      return acc + ((Number(item.price) + optionsTotal) * item.quantity);
    }, 0);
  }

  bindEvents() {
    // Abrir modal de produto ao clicar no card
    document.querySelectorAll('.product-card').forEach(card => {
      card.addEventListener('click', (e) => {
        const prodId = card.getAttribute('data-product-id');
        this.openProductModal(prodId);
      });
    });

    // Fechar modal de produto
    const closeModalBtn = document.getElementById('btn-close-modal');
    const modalOverlay = document.getElementById('product-modal-overlay');
    if (closeModalBtn && modalOverlay) {
      closeModalBtn.addEventListener('click', () => this.closeProductModal());
      modalOverlay.addEventListener('click', (e) => {
        if (e.target === modalOverlay) this.closeProductModal();
      });
    }

    // Stepper de quantidade do modal
    const btnMinus = document.getElementById('btn-modal-minus');
    const btnPlus = document.getElementById('btn-modal-plus');
    if (btnMinus && btnPlus) {
      btnMinus.addEventListener('click', () => {
        if (this.modalQuantity > 1) {
          this.modalQuantity--;
          this.updateModalPriceAndValidation();
        }
      });
      btnPlus.addEventListener('click', () => {
        this.modalQuantity++;
        this.updateModalPriceAndValidation();
      });
    }

    // Botão Adicionar do Modal
    const btnAddModal = document.getElementById('btn-confirm-add-product');
    if (btnAddModal) {
      btnAddModal.addEventListener('click', () => this.confirmAddProduct());
    }

    // Floating bar clica para abrir Drawer da sacola
    const openCartBtn = document.getElementById('btn-open-cart-drawer');
    const cartDrawerOverlay = document.getElementById('cart-drawer-overlay');
    const closeCartDrawerBtn = document.getElementById('btn-close-cart-drawer');

    if (openCartBtn && cartDrawerOverlay) {
      openCartBtn.addEventListener('click', () => {
        cartDrawerOverlay.classList.add('active');
      });
    }
    if (closeCartDrawerBtn && cartDrawerOverlay) {
      closeCartDrawerBtn.addEventListener('click', () => {
        cartDrawerOverlay.classList.remove('active');
      });
      cartDrawerOverlay.addEventListener('click', (e) => {
        if (e.target === cartDrawerOverlay) {
          cartDrawerOverlay.classList.remove('active');
        }
      });
    }
  }

  openProductModal(productId) {
    const product = this.catalog[productId];
    if (!product) return;

    this.activeProduct = product;
    this.modalQuantity = 1;

    document.getElementById('modal-product-name').textContent = product.name;
    document.getElementById('modal-product-desc').textContent = product.description || '';
    document.getElementById('modal-product-base-price').textContent = `R$ ${product.price.toFixed(2).replace('.', ',')}`;

    // Foto do produto no modal
    const imgContainer = document.getElementById('modal-product-image-container');
    const imgEl = document.getElementById('modal-product-img');
    if (imgContainer && imgEl) {
      if (product.image_url) {
        imgEl.src = product.image_url;
        imgEl.alt = product.name;
        imgContainer.style.display = 'block';
      } else {
        imgContainer.style.display = 'none';
      }
    }

    const notesInput = document.getElementById('modal-notes-input');
    if (notesInput) notesInput.value = '';

    // Renderizar grupos de opções
    const optionsContainer = document.getElementById('modal-options-container');
    optionsContainer.innerHTML = '';

    if (product.option_groups && product.option_groups.length > 0) {
      product.option_groups.forEach(group => {
        const groupBox = document.createElement('div');
        groupBox.className = 'option-group-box';
        groupBox.setAttribute('data-group-id', group.id);
        groupBox.setAttribute('data-min', group.min_options);
        groupBox.setAttribute('data-max', group.max_options);

        const badgeClass = group.is_required || group.min_options > 0 ? 'required' : 'optional';
        let badgeText = 'Opcional';
        if (group.min_options > 0 && group.min_options === group.max_options) {
          badgeText = `Obrigatório (Escolha exatamente ${group.min_options})`;
        } else if (group.min_options > 0 && group.max_options > group.min_options) {
          badgeText = `Obrigatório (Escolha de ${group.min_options} a ${group.max_options})`;
        } else if (group.min_options === 1 && group.max_options === 1) {
          badgeText = 'Obrigatório (Escolha 1)';
        } else if (group.max_options > 1) {
          badgeText = `Opcional (Até ${group.max_options})`;
        }

        let html = `
          <div class="option-group-header">
            <div>
              <strong style="color:var(--text-main); font-size:0.95rem;">${group.name}</strong>
              ${group.description ? `<p style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">${group.description}</p>` : ''}
            </div>
            <span class="group-badge ${badgeClass}">${badgeText}</span>
          </div>
          <div class="options-items-list">
        `;

        const inputType = group.max_options === 1 ? 'radio' : 'checkbox';
        const inputName = `group_${group.id}`;

        group.items.forEach(item => {
          const isAvail = item.is_available !== false;
          let priceDisplay = item.price > 0 ? `+ R$ ${item.price.toFixed(2).replace('.', ',')}` : 'Grátis';
          if (!isAvail) {
            priceDisplay = '<span style="color:#ef4444; font-size:0.8rem; font-weight:700;">(Esgotado)</span>';
          }

          html += `
            <label class="option-row" style="${!isAvail ? 'opacity:0.55; cursor:not-allowed;' : ''}">
              <span class="option-label">
                <input type="${inputType}" name="${inputName}" value="${item.id}" data-item-name="${item.name}" data-price="${item.price}" class="option-checkbox" ${!isAvail ? 'disabled' : ''}>
                <span style="${!isAvail ? 'text-decoration:line-through; color:#94a3b8;' : ''}">${item.name}</span>
              </span>
              <span class="option-price">${priceDisplay}</span>
            </label>
          `;
        });

        html += `</div>`;
        groupBox.innerHTML = html;
        optionsContainer.appendChild(groupBox);
      });

      // Ouvir mudanças nos checkboxes / radios
      optionsContainer.querySelectorAll('input').forEach(input => {
        input.addEventListener('change', (e) => {
          this.handleOptionSelection(e.target);
          this.updateModalPriceAndValidation();
        });
      });
    }

    this.updateModalPriceAndValidation();
    document.getElementById('product-modal-overlay').classList.add('active');
  }

  handleOptionSelection(changedInput) {
    const groupBox = changedInput.closest('.option-group-box');
    const max = parseInt(groupBox.getAttribute('data-max')) || 1;

    if (max > 1) {
      const checkedCount = groupBox.querySelectorAll('input:checked').length;
      if (checkedCount > max) {
        changedInput.checked = false;
        alert(`Você pode escolher no máximo ${max} opções neste grupo.`);
      }
    }
  }

  updateModalPriceAndValidation() {
    if (!this.activeProduct) return;

    let optionsTotal = 0;
    let allRequiredSatisfied = true;
    let unsatisfiedGroupName = '';
    let missingCount = 0;

    // Calcula adicionais selecionados e valida grupos
    document.querySelectorAll('.option-group-box').forEach(box => {
      const min = parseInt(box.getAttribute('data-min')) || 0;
      const checked = box.querySelectorAll('input:checked');
      if (checked.length < min) {
        allRequiredSatisfied = false;
        if (!unsatisfiedGroupName) {
          unsatisfiedGroupName = box.querySelector('strong').textContent;
          missingCount = min - checked.length;
        }
      }
      checked.forEach(input => {
        optionsTotal += parseFloat(input.getAttribute('data-price')) || 0;
      });
    });

    const unitPrice = this.activeProduct.price + optionsTotal;
    const finalTotal = unitPrice * this.modalQuantity;

    // Atualiza stepper
    document.getElementById('modal-step-quantity').textContent = this.modalQuantity;

    // Atualiza botão com mensagem dinâmica de pendência
    const btn = document.getElementById('btn-confirm-add-product');
    const btnTextSpan = btn.querySelector('span:first-child');
    if (!allRequiredSatisfied) {
      btn.disabled = true;
      btn.style.opacity = '0.65';
      if (btnTextSpan) {
        btnTextSpan.textContent = `Escolha mais ${missingCount} em "${unsatisfiedGroupName}"`;
      }
    } else {
      btn.disabled = false;
      btn.style.opacity = '1';
      if (btnTextSpan) {
        btnTextSpan.textContent = 'Adicionar';
      }
    }
    document.getElementById('modal-total-value').textContent = `R$ ${finalTotal.toFixed(2).replace('.', ',')}`;
  }

  confirmAddProduct() {
    if (!this.activeProduct) return;

    const selectedOptions = [];
    document.querySelectorAll('.option-group-box input:checked').forEach(input => {
      selectedOptions.push({
        id: parseInt(input.value),
        name: input.getAttribute('data-item-name'),
        price: parseFloat(input.getAttribute('data-price')) || 0
      });
    });

    const notes = document.getElementById('modal-notes-input').value.trim();

    this.addItem({
      productId: this.activeProduct.id,
      name: this.activeProduct.name,
      price: this.activeProduct.price,
      quantity: this.modalQuantity,
      options: selectedOptions,
      notes: notes
    });

    this.closeProductModal();
  }

  closeProductModal() {
    document.getElementById('product-modal-overlay').classList.remove('active');
    this.activeProduct = null;
  }

  renderCartUI() {
    const count = this.getItemCount();
    const subtotal = this.getSubtotal();
    const floatingBar = document.getElementById('cart-floating-bar');

    if (floatingBar) {
      if (count > 0) {
        floatingBar.classList.add('active');
        document.getElementById('cart-floating-count').textContent = `${count} ${count === 1 ? 'item' : 'itens'}`;
        document.getElementById('cart-floating-total').textContent = `R$ ${subtotal.toFixed(2).replace('.', ',')}`;
      } else {
        floatingBar.classList.remove('active');
      }
    }

    // Renderiza Drawer
    const drawerList = document.getElementById('cart-drawer-items-list');
    const drawerSubtotal = document.getElementById('cart-drawer-subtotal');
    if (drawerList) {
      drawerList.innerHTML = '';
      if (this.items.length === 0) {
        drawerList.innerHTML = '<p style="text-align:center; color:#94a3b8; padding:30px 0;">Sua sacola está vazia.</p>';
        const btnCheckout = document.getElementById('btn-drawer-checkout');
        if (btnCheckout) btnCheckout.style.display = 'none';
      } else {
        const btnCheckout = document.getElementById('btn-drawer-checkout');
        if (btnCheckout) btnCheckout.style.display = 'flex';

        this.items.forEach((item, index) => {
          const itemRow = document.createElement('div');
          itemRow.className = 'cart-item-row';

          const optionsStr = item.options.map(o => o.name).join(', ');
          const optionsPrice = item.options.reduce((sum, o) => sum + o.price, 0);
          const itemTotal = (item.price + optionsPrice) * item.quantity;

          itemRow.innerHTML = `
            <div class="cart-item-info">
              <div class="cart-item-title">${item.quantity}x ${item.name}</div>
              ${optionsStr ? `<div class="cart-item-options">+ ${optionsStr}</div>` : ''}
              ${item.notes ? `<div class="cart-item-notes">Obs: "${item.notes}"</div>` : ''}
              <div style="display:flex; gap:10px; margin-top:8px; align-items:center;">
                <div class="quantity-stepper" style="transform: scale(0.85); transform-origin: left center;">
                  <button type="button" class="btn-step" data-action="minus" data-index="${index}">-</button>
                  <span class="step-value">${item.quantity}</span>
                  <button type="button" class="btn-step" data-action="plus" data-index="${index}">+</button>
                </div>
                <button type="button" class="btn-remove-item" data-action="delete" data-index="${index}" style="background:transparent; border:none; color:#f43f5e; font-size:0.8rem; cursor:pointer;">Remover</button>
              </div>
            </div>
            <div class="cart-item-price">R$ ${itemTotal.toFixed(2).replace('.', ',')}</div>
          `;
          drawerList.appendChild(itemRow);
        });

        // Eventos nos botões de + / - e remover da sacola
        drawerList.querySelectorAll('[data-action]').forEach(btn => {
          btn.addEventListener('click', (e) => {
            const action = btn.getAttribute('data-action');
            const idx = parseInt(btn.getAttribute('data-index'));
            if (action === 'plus') this.updateQuantity(idx, 1);
            if (action === 'minus') this.updateQuantity(idx, -1);
            if (action === 'delete') this.removeItem(idx);
          });
        });
      }
    }

    if (drawerSubtotal) {
      drawerSubtotal.textContent = `R$ ${subtotal.toFixed(2).replace('.', ',')}`;
    }
  }
}

// Inicializa o carrinho com o slug da loja atual
document.addEventListener('DOMContentLoaded', () => {
  const storeSlugEl = document.getElementById('store-slug-id');
  if (storeSlugEl) {
    const slug = storeSlugEl.getAttribute('data-slug');
    window.iaCart = new IAPedidosCart(slug);
  }
});
